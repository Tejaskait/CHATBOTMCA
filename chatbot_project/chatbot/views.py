
from django.shortcuts import render
from django.http import JsonResponse
import google.generativeai as genai
from django.conf import settings


genai.configure(api_key=settings.GEMINI_API_KEY)

def chat_view(request):
    if request.method == "POST":
        user_input = request.POST.get("message", "")

       
        model = genai.GenerativeModel("gemini-1.5-flash")  

        response = model.generate_content(user_input)

        bot_reply = response.text if response else "Sorry, I couldn’t understand."
        return JsonResponse({"reply": bot_reply})

    return render(request, "chatbot/chat.html")
