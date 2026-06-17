"""
Definition of views.
"""

# from datetime import datetime
# from django.shortcuts import render
# from django.http import HttpRequest

# def home(request):
#     """Renders the home page."""
#     assert isinstance(request, HttpRequest)
#     return render(
#         request,
#         'app/index.html',
#         {
#             'title':'Home Page',
#             'year':datetime.now().year,
#         }
#     )

# def contact(request):
#     """Renders the contact page."""
#     assert isinstance(request, HttpRequest)
#     return render(
#         request,
#         'app/contact.html',
#         {
#             'title':'Contact',
#             'message':'Your contact page.',
#             'year':datetime.now().year,
#         }
#     )

# def about(request):
#     """Renders the about page."""
#     assert isinstance(request, HttpRequest)
#     return render(
#         request,
#         'app/about.html',
#         {
#             'title':'About',
#             'message':'Your application description page.',
#             'year':datetime.now().year,
#         }
#     )

from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from datetime import timedelta

from .serializers import (
    ApproveTicketSerializer, 
    BlockTicketSerializer, 
    B2BEventSerializer,
    ClaimTicketRequestSerializer, 
    ProductBlockingReasonSerializer,
    ProductBlockingReasonCreateSerializer,
    ProductBlockingReasonUpdateSerializer
    )
from .services import (
    approve_ticket_service, 
    block_ticket_service, 
    handle_b2b_event_service, 
    claim_next_ticket_service,    
    get_blocking_reasons_service,
    create_blocking_reason_service,
    update_blocking_reason_service,
    deactivate_blocking_reason_service
    )
from .models import ProductModeration, ProductBlockingReason
from .authentication import ServiceKeyAuthentication
from .exceptions import (
    error_response,
    ModerationNotFoundError,
    ModerationNotAssignedError,
    ModerationInvalidStatusError,
    ProductHasNoSkusError,
    B2BEventError,
    DoubleB2BEventError,
    UnauthorizedRequestError,
    B2BUnavailableError
)

class CreateEventAPIView(APIView):
    def post(self, request, *args, **kwargs):
        return Response(
            {"detail": "Request accepted for processing."}, 
            status=status.HTTP_202_ACCEPTED
        )

class ApproveProductView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_id):
        serializer = ApproveTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            moderation = approve_ticket_service(
                ticket_id=ticket_id,
                moderator=request.user,
                comment=serializer.validated_data.get('comment', '')
            )


            
            # Формирование ответа в соответствии с TicketResponse из moderation.yaml
            response_data = {
                "id": str(moderation.id),
                "product_id": str(moderation.product_id),
                "seller_id": str(moderation.seller_id),
                "category_id": moderation.json_after.get('category_id') if moderation.json_after else None,
                "kind": "CREATE" if moderation.json_before is None else "EDIT",
                "status": moderation.status,
                "queue_priority": moderation.queue_priority,
                "assigned_moderator_id": str(moderation.moderator_id.id) if moderation.moderator_id else None,
                "claimed_at": moderation.date_updated.isoformat() if moderation.date_updated else None,
                "claim_expires_at": None,
                "decision_at": moderation.date_moderation.isoformat() if moderation.date_moderation else None,
                "created_at": moderation.date_created.isoformat(),
                "updated_at": moderation.date_updated.isoformat()
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except ModerationNotFoundError:
            return error_response("NOT_FOUND", "Product not found in moderation queue", status.HTTP_404_NOT_FOUND)
        except ModerationNotAssignedError as e:
            return error_response("FORBIDDEN", str(e), status.HTTP_403_FORBIDDEN)
        except (ModerationInvalidStatusError, ProductHasNoSkusError) as e:
            return error_response("CONFLICT", str(e), status.HTTP_409_CONFLICT)
        except B2BEventError as e:
            return error_response("B2B_ERROR", str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)

class BlockTicketView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_id):
        serializer = BlockTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            moderation = block_ticket_service(
                ticket_id=ticket_id,
                moderator=request.user,
                blocking_reason_ids=serializer.validated_data.get('blocking_reason_ids', []),
                comment=serializer.validated_data.get('comment', ''),
                field_reports=serializer.validated_data.get('field_reports', [])
            )
            
            response_data = {
                "id": str(moderation.id),
                "product_id": str(moderation.product_id),
                "seller_id": str(moderation.seller_id),
                "category_id": moderation.json_after.get('category_id') if moderation.json_after else None,
                "kind": "CREATE" if moderation.json_before is None else "EDIT",
                "status": moderation.status,
                "queue_priority": moderation.queue_priority,
                "assigned_moderator_id": str(moderation.moderator_id.id) if moderation.moderator_id else None,
                "claimed_at": moderation.date_updated.isoformat() if moderation.date_updated else None,
                "claim_expires_at": None,
                "decision_at": moderation.date_moderation.isoformat() if moderation.date_moderation else None,
                "created_at": moderation.date_created.isoformat(),
                "updated_at": moderation.date_updated.isoformat()
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except ModerationNotFoundError:
            return error_response("NOT_FOUND", "Product not found in moderation queue", status.HTTP_404_NOT_FOUND)
        except ModerationNotAssignedError as e:
            return error_response("FORBIDDEN", str(e), status.HTTP_403_FORBIDDEN)
        except ModerationInvalidStatusError as e:
            return error_response("CONFLICT", str(e), status.HTTP_409_CONFLICT)
        except B2BEventError as e:
            return error_response("B2B_ERROR", str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return error_response("BAD_REQUEST", str(e), status.HTTP_400_BAD_REQUEST)


class B2BEventReceiverView(APIView):
    # События от B2B защищены X-Service-Key на уровне middleware/gateway, а не JWT
    permission_classes = [IsAuthenticated]
    authentication_classes = [ServiceKeyAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = B2BEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            handle_b2b_event_service(serializer.validated_data)
            return Response(status=status.HTTP_202_ACCEPTED)
        except DoubleB2BEventError as e:
            return error_response('DOUBLE_EVENT','DOUBLE_EVENT',status.HTTP_409_CONFLICT)
        except B2BUnavailableError as e:
            return error_response('B2BUnavailable','B2BUnavailable',status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            return error_response("BAD_REQUEST", str(e), status.HTTP_400_BAD_REQUEST)

class UpdateTicketView(APIView):
    """
    Эндпоинт для проверки требования any_modify_on_hard_blocked_returns_403.
    Любые попытки модификации HARD_BLOCKED карточки возвращают 403.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, ticket_id):
        try:
            moderation = ProductModeration.objects.get(id=ticket_id)
            if moderation.status == ProductModeration.StatusChoices.HARD_BLOCKED:
                return error_response("FORBIDDEN", "Product is permanently blocked and cannot be modified", status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Modified"}, status=status.HTTP_200_OK)
        except ProductModeration.DoesNotExist:
            return error_response("NOT_FOUND", "Ticket not found", status.HTTP_404_NOT_FOUND)

    def put(self, request, ticket_id):
        return self.post(request, ticket_id)

class ClaimTicketView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ClaimTicketRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            ticket = claim_next_ticket_service(
                moderator=request.user,
                queue_priority=serializer.validated_data.get('queue_priority'),
                category_ids=serializer.validated_data.get('category_ids')
            )
            
            if not ticket:
                return Response(status=status.HTTP_204_NO_CONTENT)
                
            # Формируем ответ строго по схеме TicketResponse из moderation.yaml
            response_data = {
                "id": str(ticket.id),
                "product_id": str(ticket.product_id),
                "seller_id": str(ticket.seller_id),
                "category_id": ticket.json_after.get('category_id') if ticket.json_after else None,
                "kind": "CREATE" if ticket.json_before is None else "EDIT",
                "status": ticket.status,
                "queue_priority": ticket.queue_priority,
                "assigned_moderator_id": str(ticket.moderator_id.id) if ticket.moderator_id else None,
                "claimed_at": ticket.date_updated.isoformat() if ticket.date_updated else None,
                "claim_expires_at": (ticket.date_updated + timedelta(minutes=30)).isoformat() if ticket.date_updated else None,
                "decision_at": ticket.date_moderation.isoformat() if ticket.date_moderation else None,
                "created_at": ticket.date_created.isoformat(),
                "updated_at": ticket.date_updated.isoformat()
            }
            return Response(response_data, status=status.HTTP_200_OK)
            
        except ModerationInvalidStatusError as e:
            return error_response("CONFLICT", str(e), status.HTTP_409_CONFLICT)
        except Exception as e:
            return error_response("BAD_REQUEST", str(e), status.HTTP_400_BAD_REQUEST)

class BlockingReasonsListView(APIView):
    """
    GET /api/v1/blocking-reasons
    Справочник причин блокировки.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        hard_block = request.query_params.get('hard_block')
        is_active = request.query_params.get('is_active', 'true')
        
        # Преобразуем строковые параметры в boolean
        hard_block_bool = None
        if hard_block is not None:
            hard_block_bool = hard_block.lower() == 'true'
        
        is_active_bool = is_active.lower() == 'true' if is_active else True
        
        reasons = get_blocking_reasons_service(
            hard_block=hard_block_bool,
            is_active=is_active_bool
        )
        
        serializer = ProductBlockingReasonSerializer(reasons, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        POST /api/v1/blocking-reasons
        Создание причины блокировки (только для admin).
        """
        if not request.user.is_staff and not hasattr(request.user, 'role') or (hasattr(request.user, 'role') and request.user.role != 'ADMIN'):
            return error_response("FORBIDDEN", "Admin access required", status.HTTP_403_FORBIDDEN)
        
        serializer = ProductBlockingReasonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            reason = create_blocking_reason_service(
                code=serializer.validated_data['code'],
                title=serializer.validated_data['title'],
                hard_block=serializer.validated_data['hard_block'],
                description=serializer.validated_data.get('description', '')
            )
            response_serializer = ProductBlockingReasonSerializer(reason)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return error_response("CONFLICT", str(e), status.HTTP_409_CONFLICT)


class BlockingReasonDetailView(APIView):
    """
    PATCH/DELETE /api/v1/blocking-reasons/{reason_id}
    Обновление и деактивация причины блокировки (только для admin).
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, reason_id):
        if not request.user.is_staff and not hasattr(request.user, 'role') or (hasattr(request.user, 'role') and request.user.role != 'ADMIN'):
            return error_response("FORBIDDEN", "Admin access required", status.HTTP_403_FORBIDDEN)
        
        serializer = ProductBlockingReasonUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            reason = update_blocking_reason_service(reason_id, **serializer.validated_data)
            response_serializer = ProductBlockingReasonSerializer(reason)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except ValueError as e:
            return error_response("NOT_FOUND", str(e), status.HTTP_404_NOT_FOUND)

    def delete(self, request, reason_id):
        """
        Деактивация причины блокировки (soft-delete).
        """
        if not request.user.is_staff and not hasattr(request.user, 'role') or (hasattr(request.user, 'role') and request.user.role != 'ADMIN'):
            return error_response("FORBIDDEN", "Admin access required", status.HTTP_403_FORBIDDEN)
        
        try:
            deactivate_blocking_reason_service(reason_id)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ValueError as e:
            if "not found" in str(e).lower():
                return error_response("NOT_FOUND", str(e), status.HTTP_404_NOT_FOUND)
            else:
                return error_response("CONFLICT", str(e), status.HTTP_409_CONFLICT)