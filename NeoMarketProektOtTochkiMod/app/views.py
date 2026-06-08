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

from .serializers import ApproveTicketSerializer
from .services import approve_ticket_service, get_kind
from .exceptions import (
    error_response,
    ModerationNotFoundError,
    ModerationNotAssignedError,
    ModerationInvalidStatusError,
    ProductHasNoSkusError,
    B2BEventError
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
                "kind": get_kind(moderation.product_id),
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