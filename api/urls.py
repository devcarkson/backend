from django.urls import path
from . import views

urlpatterns = [
    path('news', views.news_list, name='news_list'),
    path('news/<str:item_id>', views.news_detail, name='news_detail'),
    path('trending', views.trending, name='trending'),
    path('music', views.music_search, name='music_search'),
    path('music/<int:track_id>', views.music_detail, name='music_detail'),
]
