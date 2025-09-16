# chatbot/views.py
import json
from datetime import datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.utils.crypto import get_random_string
import google.generativeai as genai

# Configure Gemini client (uses GEMINI_API_KEY from settings)
genai.configure(api_key=getattr(settings, "GEMINI_API_KEY", None))
MODEL_NAME = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")

# Single Mongo collection for all chats
chat_collection = settings.MONGO_DB["chats"]


def ensure_user_doc(user_id: str):
    """Ensure there's a single document for this user (user_id + chat_history array)."""
    chat_collection.update_one(
        {"user_id": user_id},
        {"$setOnInsert": {"user_id": user_id, "chat_history": []}},
        upsert=True,
    )


def generate_bot_reply(user_text: str) -> str:
    """Call Gemini model and return a text reply. If the model raises, return error text."""
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        # This follows the pattern you already used in the project.
        response = model.generate_content(user_text)
        # the SDK response may store text in `.text`; fallback to string conversion
        return getattr(response, "text", str(response))
    except Exception as e:
        # Return an explainable error that will also be stored in history (so you can debug)
        return f"[Model error] {str(e)}"


def chat_view(request):
    """
    GET -> render the chat page (loads UI). 
    POST -> accepts JSON {message, session_id?} and returns {"reply", "session_id"}.
    """
    # Ensure a user_id in session
    user_id = request.session.get("user_id")
    if not user_id:
        user_id = get_random_string(12)
        request.session["user_id"] = user_id

    if request.method == "GET":
        # render the UI template
        return render(request, "chatbot/chat.html")

    # POST (expect JSON body)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        # fallback for legacy form posts
        data = request.POST.dict()

    message = (data.get("message") or "").strip()
    if not message:
        return HttpResponseBadRequest("No message provided")

    session_id = data.get("session_id") or None

    # generate the bot reply (wrap call so view remains tidy)
    bot_reply = generate_bot_reply(message)

    # Ensure the user document exists
    ensure_user_doc(user_id)

    if not session_id:
        # New session: create a session object with this first message pair
        session_id = get_random_string(12)
        session_obj = {
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
            "messages": [{"user": message, "bot": bot_reply}],
        }
        chat_collection.update_one({"user_id": user_id}, {"$push": {"chat_history": session_obj}})
    else:
        # Try to append to existing session's messages array
        res = chat_collection.update_one(
            {"user_id": user_id, "chat_history.session_id": session_id},
            {"$push": {"chat_history.$.messages": {"user": message, "bot": bot_reply}}},
        )
        if res.matched_count == 0:
            # if session doesn't exist for some reason, create it
            session_obj = {
                "session_id": session_id,
                "created_at": datetime.utcnow().isoformat(),
                "messages": [{"user": message, "bot": bot_reply}],
            }
            chat_collection.update_one({"user_id": user_id}, {"$push": {"chat_history": session_obj}})

    return JsonResponse({"reply": bot_reply, "session_id": session_id})


def history_list(request):
    """Return a compact list of sessions for current user (session_id, created_at, preview)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"sessions": []})

    doc = chat_collection.find_one({"user_id": user_id}, {"_id": 0, "chat_history": 1})
    if not doc:
        return JsonResponse({"sessions": []})

    sessions = []
    for s in doc.get("chat_history", []):
        last_msg = s.get("messages", [])[-1] if s.get("messages") else None
        preview = ""
        if last_msg:
            # show small preview combining last user or bot
            preview = (last_msg.get("user") or "")[:60]
        sessions.append({
            "session_id": s.get("session_id"),
            "created_at": s.get("created_at"),
            "preview": preview
        })

    # newest first
    sessions = list(reversed(sessions))
    return JsonResponse({"sessions": sessions})


def history_detail(request, session_id):
    """Return the messages array for a specific session_id for the current user."""
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"history": []})

    # Using positional projection so only the matching session is returned
    doc = chat_collection.find_one(
        {"user_id": user_id, "chat_history.session_id": session_id},
        {"_id": 0, "chat_history.$": 1}
    )
    if not doc or "chat_history" not in doc:
        return JsonResponse({"history": []})

    session = doc["chat_history"][0]
    return JsonResponse({"history": session.get("messages", []), "created_at": session.get("created_at")})

def history_delete(request, session_id):
    """
    Delete a session (session_id) from the current user's chat_history.
    Expects POST. Returns JSON: {"deleted": True, "session_id": ...} or error.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "no user_id in session"}, status=400)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    # Remove the session object from the chat_history array
    res = chat_collection.update_one(
        {"user_id": user_id},
        {"$pull": {"chat_history": {"session_id": session_id}}}
    )

    if res.modified_count > 0:
        return JsonResponse({"deleted": True, "session_id": session_id})
    else:
        # nothing removed: session not found
        return JsonResponse({"deleted": False, "error": "session not found"}, status=404)
