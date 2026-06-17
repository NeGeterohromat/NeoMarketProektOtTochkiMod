"""
Definition of urls for NeoMarketProektOtTochkiMod.
"""

from datetime import datetime
from django.urls import path
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from app import forms, views

from app.views import BlockTicketView, B2BEventReceiverView, CreateEventAPIView, ApproveProductView, UpdateTicketView, ClaimTicketView, BlockingReasonDetailView, BlockingReasonsListView


urlpatterns = [
    # path('', views.home, name='home'),
    # path('contact/', views.contact, name='contact'),
    # path('about/', views.about, name='about'),
    # path('login/',
    #      LoginView.as_view
    #      (
    #          template_name='app/login.html',
    #          authentication_form=forms.BootstrapAuthenticationForm,
    #          extra_context=
    #          {
    #              'title': 'Log in',
    #              'year' : datetime.now().year,
    #          }
    #      ),
    #      name='login'),
    # path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('admin/', admin.site.urls),
    path('api/v1/tickets/<uuid:ticket_id>/block/', BlockTicketView.as_view(), name='block-ticket'),
    path('api/v1/tickets/<uuid:ticket_id>/', UpdateTicketView.as_view(), name='update-ticket'),
    path('api/v1/b2b/events/', B2BEventReceiverView.as_view(), name='b2b-events'),
    path(
        'api/v1/tickets/<uuid:ticket_id>/approve', 
        ApproveProductView.as_view(), 
        name='approve-product'
    ),
    path('api/v1/queue/claim/', ClaimTicketView.as_view(), name='claim-ticket'),
    path('api/v1/blocking-reasons', BlockingReasonsListView.as_view(), name='blocking-reasons-list'),
    path('api/v1/blocking-reasons/<uuid:reason_id>', BlockingReasonDetailView.as_view(), name='blocking-reason-detail'),
]
