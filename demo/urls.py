"""django_test URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from oscar.app import application

try:
    from django.urls import include
    from django.urls import path_re as url
except ImportError:
    from django.conf.urls import url
    from django.conf.urls import include

#from .views import PaymentView, PayObView, SelectView


urlpatterns = [
    url('^i18n/', include('django.conf.urls.i18n')),
    url('^admin/', admin.site.urls),
    url(r'', application.urls),
]
