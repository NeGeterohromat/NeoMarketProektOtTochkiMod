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

from rest_framework import viewsets, generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Moderation


class CreateEventAPIView(APIView):
    def post(self, request, *args, **kwargs):
        return Response(
            {"detail": "Request accepted for processing."}, 
            status=status.HTTP_202_ACCEPTED
        )
    
