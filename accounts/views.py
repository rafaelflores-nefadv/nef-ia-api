from django.contrib.auth import views as auth_views

from .forms import AdminAuthenticationForm


class AdminLoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True
    authentication_form = AdminAuthenticationForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Entrar"
        return context
