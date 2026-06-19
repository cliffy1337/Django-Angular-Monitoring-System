from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.shortcuts import redirect
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

def root(request):
    return redirect('/api/docs/')

urlpatterns = [
    path('', root),
    path('health/', lambda request: HttpResponse('ok'), name='health'),
    path('admin_portal/', admin.site.urls),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/v1/', include('apps.monitors.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns