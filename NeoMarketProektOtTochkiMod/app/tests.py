import uuid
from unittest.mock import patch, Mock

from django.test import override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.urls import reverse

from .models import ProductModeration, ProductBlockingReason

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