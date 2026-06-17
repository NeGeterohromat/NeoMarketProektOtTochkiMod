import uuid
from unittest.mock import patch, Mock

from django.test import override_settings
import threading
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient, APITransactionTestCase
from rest_framework import status
from django.urls import reverse
from django.conf import settings
from django.db import connection

from .models import ProductModeration, ProductBlockingReason, ProductModerationFieldReport

User = get_user_model()

@override_settings(B2B_URL='http://mock-b2b.local', MOD_TO_B2B_KEY='test-secret-key')
class ApproveTicketTests(APITestCase):
    def setUp(self):
        self.moderator = User.objects.create_user(username='mod1', password='password123')
        self.other_moderator = User.objects.create_user(username='mod2', password='password123')
        
        self.product_id = uuid.uuid4()
        self.seller_id = uuid.uuid4()
        self.category_id = uuid.uuid4()
        
        self.moderation = ProductModeration.objects.create(
            product_id=self.product_id,
            seller_id=self.seller_id,
            status=ProductModeration.StatusChoices.IN_REVIEW,
            queue_priority=2,
            json_after={"category_id": str(self.category_id)},
            moderator_id=self.moderator
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.moderator)
        self.url = reverse('approve-product',kwargs={'ticket_id':self.moderation.id})

    @patch('app.services.requests.get')
    @patch('app.services.requests.post')
    def test_approve_transitions_to_moderated_and_emits_event(self, mock_post_event, mock_get_product):
        # Happy path
        mock_get_product.return_value.status_code = 200
        mock_get_product.return_value.json.side_effect = [{"skus": [{"id": str(uuid.uuid4()), "price": 1000}]},{'status':'CREATED'}]
        mock_post_event.return_value.status_code = 204

        response = self.client.post(self.url, {"comment": "Товар соответствует требованиям"}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.moderation.refresh_from_db()
        self.assertEqual(self.moderation.status, ProductModeration.StatusChoices.APPROVED)
        self.assertEqual(self.moderation.moderator_comment, "Товар соответствует требованиям")
        self.assertIsNone(self.moderation.blocking_reason)
        
        # Проверка вызова B2B event
        mock_post_event.assert_called_once()
        call_kwargs = mock_post_event.call_args[1]
        self.assertEqual(call_kwargs['json']['idempotency_key'], str(self.moderation.id))
        self.assertEqual(call_kwargs['json']['product_id'], str(self.moderation.product_id))
        self.assertEqual(call_kwargs['json']['event_type'], 'MODERATED')
        self.assertEqual(call_kwargs['json']['moderator_comment'], "Товар соответствует требованиям")
        self.assertIsNone(call_kwargs['json']['blocking_reason_id'])
        self.assertEqual(call_kwargs['json']['hard_block'], False)


        

    @patch('app.services.requests.get')
    def test_approve_others_card_returns_403(self, mock_get):
        # Unhappy: чужая карточка
        self.moderation.moderator_id = self.other_moderator
        self.moderation.save()
        
        response = self.client.post(self.url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['code'], 'FORBIDDEN')
        self.assertIn('not assigned to you', response.data['message'])

    @patch('app.services.requests.get')
    def test_approve_after_edited_returns_409(self, mock_get):
        # Unhappy: продавец отредактировал, статус сбросился (или не IN_REVIEW)
        self.moderation.status = ProductModeration.StatusChoices.PENDING
        self.moderation.save()
        
        response = self.client.post(self.url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'CONFLICT')
        self.assertIn('not in review status', response.data['message'])

    @patch('app.services.requests.get')
    def test_approve_without_sku_returns_409(self, mock_get):
        # Unhappy: товар без SKU
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"skus": []} # 0 SKU
        
        response = self.client.post(self.url, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'CONFLICT')
        self.assertIn('no SKUs', response.data['message'])

    @patch('app.services.requests.get')
    @patch('app.services.requests.post')
    def test_string_url_works(self, mock_post_event, mock_get_product):
        mock_get_product.return_value.status_code = 200
        mock_get_product.return_value.json.side_effect = [{"skus": [{"id": str(uuid.uuid4()), "price": 1000}]},{'status':'CREATED'}]
        mock_post_event.return_value.status_code = 204
        url = f'/api/v1/tickets/{self.moderation.id}/approve'
        response = self.client.post(url,{"comment": "Товар соответствует требованиям"}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

class HardBlockFlowTests(APITestCase):
    def setUp(self):
        self.moderator = User.objects.create_user(username='moderator', password='pass')
        self.reason = ProductBlockingReason.objects.create(
            id=uuid.uuid4(),
            title="Контрафактный товар",
            hard_block=True
        )
        self.ticket = ProductModeration.objects.create(
            id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            seller_id=uuid.uuid4(),
            status=ProductModeration.StatusChoices.IN_REVIEW,
            queue_priority=3,
            json_after={"category_id": str(uuid.uuid4())},
            moderator_id=self.moderator
        )
        self.client.force_authenticate(user=self.moderator)

    @patch('app.services.requests.post')
    def test_hard_block_transitions_to_terminal_and_emits_event(self, mock_post):
        """Happy path: статус переходит в HARD_BLOCKED, событие уходит в B2B."""
        mock_post.return_value.status_code = 204

        url = f"/api/v1/tickets/{self.ticket.id}/block/"
        data = {
            "blocking_reason_ids": [str(self.reason.id)],
            "comment": "Hard block test"
        }
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, ProductModeration.StatusChoices.HARD_BLOCKED)
        
        self.assertTrue(mock_post.called)
        call_args = mock_post.call_args
        self.assertIn("/api/v1/moderation/events", call_args[0][0])
        payload = call_args[1]['json']
        self.assertEqual(payload['event_type'], 'BLOCKED')

    @patch('app.services.requests.post')
    def test_hard_block_event_carries_hard_block_true(self, mock_post):
        """Флаг hard_block в событии строго равен True."""
        mock_post.return_value.status_code = 204
        
        url = f"/api/v1/tickets/{self.ticket.id}/block/"
        data = {
            "blocking_reason_ids": [str(self.reason.id)],
            "comment": "Hard block test"
        }
        self.client.post(url, data, format='json')
        
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        self.assertTrue(payload['hard_block'])

    def test_any_modify_on_hard_blocked_returns_403(self):
        """Защита терминальности: любые POST/PUT на карточку возвращают 403."""
        self.ticket.status = ProductModeration.StatusChoices.HARD_BLOCKED
        self.ticket.save()
        
        url = f"/api/v1/tickets/{self.ticket.id}/"
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        response = self.client.put(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_edited_event_on_hard_blocked_is_ignored(self):
        """Событие EDITED от B2B не выводит товар из терминального статуса."""
        self.ticket.status = ProductModeration.StatusChoices.HARD_BLOCKED
        self.ticket.save()
        
        url = "/api/v1/b2b/events/"
        data = {
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-10T10:00:00Z",
            "payload": {
                "product_id": str(self.ticket.product_id)
            }
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, ProductModeration.StatusChoices.HARD_BLOCKED)

    def test_deleted_event_removes_hard_blocked(self):
        """Событие DELETED удаляет запись из Moderation."""
        self.ticket.status = ProductModeration.StatusChoices.HARD_BLOCKED
        self.ticket.save()
        
        url = "/api/v1/b2b/events/"
        data = {
            "event_type": "PRODUCT_DELETED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-10T10:00:00Z",
            "payload": {
                "product_id": str(self.ticket.product_id)
            }
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        
        self.assertFalse(ProductModeration.objects.filter(id=self.ticket.id).exists())

class B2BEventFlowTests(APITestCase):
    """
    Тесты канонического флоу "приём событий товара" от B2B.
    """
    def setUp(self):
        self.url = reverse('b2b-events')
        # Заголовок межсервисной авторизации согласно moderation.yaml
        self.auth_headers = {'X-Service-Key': settings.B2B_TO_MOD_KEY}
        self.product_id = uuid.uuid4()
        self.seller_id = uuid.uuid4()
        
    def _mock_b2b_product_response(self):
        """Возвращает мок ответа от B2B Public Catalog."""
        return {
            'seller_id': str(self.seller_id),
            'category_id': str(uuid.uuid4()),
            'status': 'MODERATED',
            'skus': [{'id': str(uuid.uuid4())}]
        }

    @patch('app.services.requests.get')
    def test_created_pending(self, mock_get):
        """created_pending — событие CREATED создаёт карточку в PENDING."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = self._mock_b2b_product_response()
        
        payload = {
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-11T10:00:00Z",
            "payload": {
                "product_id": str(self.product_id),
                "seller_id": str(self.seller_id),
                "json_after": {"title": "New Product"}
            }
        }
        
        response = self.client.post(self.url, payload, format='json', headers=self.auth_headers)
        self.assertEqual(response.status_code, 202)
        
        # Проверяем, что карточка создана в статусе PENDING
        self.assertTrue(
            ProductModeration.objects.filter(
                product_id=self.product_id, 
                status=ProductModeration.StatusChoices.PENDING
            ).exists()
        )

    @patch('app.services.requests.get')
    def test_edited_returns_to_review(self, mock_get):
        """edited_returns_to_review — EDITED после MODERATED/BLOCKED возвращает карточку в очередь (PENDING)."""
        # Создаем карточку в статусе APPROVED (аналог MODERATED)
        ProductModeration.objects.create(
            product_id=self.product_id,
            seller_id=self.seller_id,
            status=ProductModeration.StatusChoices.APPROVED,
            queue_priority=3,
            json_after={"title": "Old Title"}
        )
        
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = self._mock_b2b_product_response()
        
        payload = {
            "event_type": "PRODUCT_EDITED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-11T10:00:00Z",
            "payload": {
                "product_id": str(self.product_id),
                "seller_id": str(self.seller_id),
                "json_before": {"title": "Old Title"},
                "json_after": {"title": "New Title"}
            }
        }
        
        response = self.client.post(self.url, payload, format='json', headers=self.auth_headers)
        self.assertEqual(response.status_code, 202)
        
        mod = ProductModeration.objects.get(product_id=self.product_id)
        self.assertEqual(mod.status, ProductModeration.StatusChoices.PENDING)
        # Несуществующее (явно переданное при создании) поле title перенеслось в json_before, а json_after содержит ответ от b2b
        self.assertTrue('title' in mod.json_before)
        self.assertFalse('title' in mod.json_after)

    def test_deleted_archived(self):
        """deleted_archived — DELETED уводит карточку из очереди (удаляет из БД)."""
        ProductModeration.objects.create(
            product_id=self.product_id,
            seller_id=self.seller_id,
            status=ProductModeration.StatusChoices.PENDING,
            queue_priority=3,
            json_after={}
        )
        
        payload = {
            "event_type": "PRODUCT_DELETED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-11T10:00:00Z",
            "payload": {
                "product_id": str(self.product_id)
            }
        }
        
        response = self.client.post(self.url, payload, format='json', headers=self.auth_headers)
        self.assertEqual(response.status_code, 202)
        
        # Карточка должна быть удалена
        self.assertFalse(ProductModeration.objects.filter(product_id=self.product_id).exists())

    @patch('app.services.requests.get')
    def test_duplicate_event_no_side_effects(self, mock_get):
        """duplicate_event_no_side_effects — повторное событие с тем же ключом -> 202 без побочных эффектов."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = self._mock_b2b_product_response()
        
        idem_key = str(uuid.uuid4())
        payload = {
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": idem_key,
            "occurred_at": "2026-06-11T10:00:00Z",
            "payload": {
                "product_id": str(self.product_id),
                "seller_id": str(self.seller_id),
                "json_after": {"title": "Test"}
            }
        }
        
        # Первый запрос
        response1 = self.client.post(self.url, payload, format='json', headers=self.auth_headers)
        self.assertEqual(response1.status_code, 202)
        
        # Повторный запрос с тем же idempotency_key
        response2 = self.client.post(self.url, payload, format='json', headers=self.auth_headers)
        
        # По заданию: повторное событие должно возвращать 200/202 без побочных эффектов.
        # Ваш код сейчас возвращает 409 (DoubleB2BEventError). 
        # Тест написан на корректное по заданию поведение.
        self.assertIn(response2.status_code, [200, 202])
        self.assertEqual(ProductModeration.objects.filter(product_id=self.product_id).count(), 1)

    def test_missing_service_header_401(self):
        """missing_service_header_401 — запрос без межсервисного заголовка -> 401."""
        payload = {
            "event_type": "PRODUCT_CREATED",
            "idempotency_key": str(uuid.uuid4()),
            "occurred_at": "2026-06-11T10:00:00Z",
            "payload": {"product_id": str(self.product_id)}
        }
        
        # Намеренно не передаем заголовок X-Service-Key
        response = self.client.post(self.url, payload, format='json')
        
        # Должен вернуться 401 Unauthorized
        self.assertEqual(response.status_code, 401)

class SoftBlockTests(APITestCase):
    def setUp(self):
        # Создаем двух модераторов (один для владельца тикета, второй для проверки 403)
        self.moderator1 = User.objects.create_user(username='mod1', password='password', email='mod1@test.com')
        self.moderator2 = User.objects.create_user(username='mod2', password='password', email='mod2@test.com')
        
        # Создаем причины блокировки (soft и hard)
        self.soft_reason = ProductBlockingReason.objects.create(
            id=uuid.uuid4(),
            title="Низкое качество фото",
            hard_block=False
        )
        self.hard_reason = ProductBlockingReason.objects.create(
            id=uuid.uuid4(),
            title="Запрещенный товар",
            hard_block=True
        )
        
        # Создаем тестовый тикет модерации в статусе IN_REVIEW, привязанный к moderator1
        self.product_id = uuid.uuid4()
        self.seller_id = uuid.uuid4()
        
        self.moderation = ProductModeration.objects.create(
            id=uuid.uuid4(),
            product_id=self.product_id,
            seller_id=self.seller_id,
            status=ProductModeration.StatusChoices.IN_REVIEW,
            queue_priority=2,
            json_after={"title": "Test Product", "category_id": str(uuid.uuid4())},
            moderator_id=self.moderator1
        )
        
        self.url = reverse('block-ticket', kwargs={'ticket_id': self.moderation.id})

    @patch('app.services.requests.post')
    def test_soft_block_transitions_to_blocked_with_field_reports(self, mock_post):
        """
        soft_block_transitions_to_blocked_with_field_reports: 
        Happy path. Тикет переходит в BLOCKED, сохраняются field_reports.
        """
        mock_post.return_value.status_code = 204  # Эмуляция успешного ответа B2B
        
        self.client.force_authenticate(user=self.moderator1)
        
        payload = {
            "blocking_reason_ids": [str(self.soft_reason.id)],
            "comment": "Пожалуйста, загрузите фото в лучшем качестве",
            "field_reports": [
                {
                    "field_path": "images[0].url",
                    "message": "Фото размыто",
                    "severity": "ERROR"
                },
                {
                    "field_path": "title",
                    "message": "Слишком короткое название",
                    "severity": "WARNING"
                }
            ]
        }
        
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 200)
        
        # Проверяем изменение статуса и привязку причины
        self.moderation.refresh_from_db()
        self.assertEqual(self.moderation.status, ProductModeration.StatusChoices.BLOCKED)
        self.assertEqual(self.moderation.blocking_reason, self.soft_reason)
        
        # Проверяем, что field_reports сохранились в БД
        reports = ProductModerationFieldReport.objects.filter(product_moderation=self.moderation)
        self.assertEqual(reports.count(), 2)

    @patch('app.services.requests.post')
    def test_soft_block_emits_event_to_b2b(self, mock_post):
        """
        soft_block_emits_event_to_b2b: 
        Проверяем, что событие BLOCKED с hard_block=false уходит в B2B.
        """
        mock_post.return_value.status_code = 204
        
        self.client.force_authenticate(user=self.moderator1)
        
        payload = {
            "blocking_reason_ids": [str(self.soft_reason.id)],
            "comment": "Исправьте описание"
        }
        
        self.client.post(self.url, payload, format='json')
        
        # Проверяем факт вызова B2B и содержимое payload
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('/api/v1/moderation/events', args[0])
        
        event_payload = kwargs['json']
        self.assertEqual(event_payload['event_type'], 'BLOCKED')
        self.assertFalse(event_payload['hard_block']) # Soft block -> hard_block is False
        self.assertEqual(event_payload['blocking_reason_id'], str(self.soft_reason.id))

    def test_soft_block_unknown_reason_returns_400(self):
        """
        soft_block_unknown_reason_returns_400: 
        Несуществующий blocking_reason_id возвращает 400.
        """
        self.client.force_authenticate(user=self.moderator1)
        
        payload = {
            "blocking_reason_ids": [str(uuid.uuid4())], # Несуществующий UUID
            "comment": "Тест"
        }
        
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_soft_block_others_card_returns_403(self):
        """
        soft_block_others_card_returns_403: 
        Попытка заблокировать чужую карточку возвращает 403.
        """
        # Аутентифицируемся под moderator2, но тикет принадлежит moderator1
        self.client.force_authenticate(user=self.moderator2)
        
        payload = {
            "blocking_reason_ids": [str(self.soft_reason.id)],
            "comment": "Тест"
        }
        
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 403)

    def test_soft_block_invalid_field_name_returns_400(self):
        """
        soft_block_invalid_field_name_returns_400: 
        Поле field_name вне допустимого enum возвращает 400.
        """
        self.client.force_authenticate(user=self.moderator1)
        
        payload = {
            "blocking_reason_ids": [str(self.soft_reason.id)],
            "comment": "Тест",
            "field_reports": [
                {
                    "field_path": "totally_invalid_enum_value", 
                    "message": "Невалидное поле"
                }
            ]
        }
        
        response = self.client.post(self.url, payload, format='json')
        self.assertEqual(response.status_code, 400)

class ClaimTicketTests(APITransactionTestCase):
    def setUp(self):
        self.moderator1 = User.objects.create_user(username='mod1', password='pass')
        self.moderator2 = User.objects.create_user(username='mod2', password='pass')
        self.url = '/api/v1/queue/claim/'
        
        # Создаем тикеты с разными приоритетами и временем обновления
        self.ticket1 = ProductModeration.objects.create(
            product_id='00000000-0000-0000-0000-000000000001',
            seller_id='00000000-0000-0000-0000-000000000001',
            status=ProductModeration.StatusChoices.PENDING,
            queue_priority=2,
            json_after={'category_id': '00000000-0000-0000-0000-000000000001'}
        )
        # Имитируем, что ticket1 очень старый
        ProductModeration.objects.filter(id=self.ticket1.id).update(
            date_updated=timezone.now() - timedelta(hours=2)
        )
        
        self.ticket2 = ProductModeration.objects.create(
            product_id='00000000-0000-0000-0000-000000000002',
            seller_id='00000000-0000-0000-0000-000000000001',
            status=ProductModeration.StatusChoices.PENDING,
            queue_priority=1, # Высший приоритет
            json_after={'category_id': '00000000-0000-0000-0000-000000000001'}
        )
        # Имитируем, что ticket2 новее
        ProductModeration.objects.filter(id=self.ticket2.id).update(
            date_updated=timezone.now() - timedelta(hours=1)
        )

        self.ticket3 = ProductModeration.objects.create(
            product_id='00000000-0000-0000-0000-000000000003',
            seller_id='00000000-0000-0000-0000-000000000003',
            status=ProductModeration.StatusChoices.PENDING,
            queue_priority=2,
            json_after={'category_id': '00000000-0000-0000-0000-000000000001'}
        )

    def test_next_returns_oldest_pending(self):
        """Самая старая PENDING карточка переходит в IN_REVIEW"""
        self.client.force_authenticate(user=self.moderator1)
        # Запрашиваем конкретно приоритет 2
        response = self.client.post(self.url, {'queue_priority': 2})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.ticket1.id))
        self.assertEqual(response.data['status'], 'IN_REVIEW')
        self.assertEqual(response.data['assigned_moderator_id'], str(self.moderator1.id))

    def test_concurrent_two_moderators_get_different_cards(self):
        """Две сессии не получают одну карточку (эмуляция через threading)"""
        results = {}
        def claim_ticket(user, user_id):
            from rest_framework.test import APIClient
            client = APIClient()
            client.force_authenticate(user=user)
            response = client.post(self.url)
            results[user_id] = response.data.get('id') if response.status_code == 200 else None
            connection.close() # Важно закрывать соединение в потоках

        t1 = threading.Thread(target=claim_ticket, args=(self.moderator1, 1))
        t2 = threading.Thread(target=claim_ticket, args=(self.moderator2, 2))
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # Оба модератора должны получить по карточке, и они должны быть разными
        self.assertIsNotNone(results[1])
        self.assertIsNotNone(results[2])
        self.assertNotEqual(results[1], results[2])

    def test_empty_queue_returns_204(self):
        """Пустая очередь возвращает 204"""
        ProductModeration.objects.all().delete()
        self.client.force_authenticate(user=self.moderator1)
        
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_moderator_already_has_in_review_returns_409(self):
        """Попытка взять вторую карточку с активной IN_REVIEW отклоняется"""
        self.client.force_authenticate(user=self.moderator1)
        
        # Берем первый тикет
        response1 = self.client.post(self.url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        # Пытаемся взять второй
        response2 = self.client.post(self.url)
        self.assertEqual(response2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response2.data['code'], 'CONFLICT')