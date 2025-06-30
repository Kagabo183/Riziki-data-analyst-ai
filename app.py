from flask import Flask, render_template, request, jsonify, session
from datetime import datetime
import os
import uuid
import logging
import google.generativeai as genai
import pandas as pd

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['TEMPLATES_AUTO_RELOAD'] = True

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Gemini AI setup
try:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCU6fYW1NwkrVL8BvEzO7SbIF9DONC_I1Q")
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(model_name="gemini-1.5-flash")
    logger.info("Gemini AI initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Gemini: {str(e)}")
    gemini_model = None

@app.template_filter('datetimeformat')
def format_datetime(value, format='%b %d, %H:%M'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime(format)
    return value

def init_conversations():
    """Initialize conversation data structure in session if missing."""
    if 'conversations' not in session:
        session['conversations'] = {'current': None, 'list': []}
        session.modified = True
        logger.debug("Initialized conversations in session")

def create_new_conversation():
    """Create a new conversation object and add to session."""
    conv_id = str(uuid.uuid4())
    new_conv = {
        'id': conv_id,
        'title': 'New Conversation',
        'messages': [{
            'sender': 'ai',
            'content': "👋 Hello! I'm your Data Analysis Assistant. How can I help you today?",
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_file': False
        }],
        'created_at': datetime.now().isoformat(),
        'file_info': None,
        'language': 'en'  # Default language English
    }
    session['conversations']['list'].append(new_conv)
    session['conversations']['current'] = conv_id
    session.modified = True
    logger.debug(f"Created new conversation with id {conv_id}")
    return new_conv

@app.route('/')
def index():
    init_conversations()
    conv_id = request.args.get('conversation')
    if conv_id:
        # Set current conversation if it exists
        if any(c['id'] == conv_id for c in session['conversations']['list']):
            session['conversations']['current'] = conv_id
            session.modified = True
        else:
            logger.warning(f"Conversation id {conv_id} not found in session.")
            # Optionally create a new conversation or ignore
    if not session['conversations']['list']:
        create_new_conversation()
    return render_template(
        'index.html',
        conversations=session['conversations']['list'],
        current_conversation=session['conversations']['current']
    )

@app.route('/new_chat', methods=['POST'])
def new_chat():
    init_conversations()
    new_conv = create_new_conversation()
    return jsonify({'success': True, 'conversation': new_conv})

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        conv_id = data.get('conversation_id')

        if not user_message:
            return jsonify({'error': 'No message provided'}), 400

        conversation = next((c for c in session['conversations']['list'] if c['id'] == conv_id), None)
        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

        # Initialize language if not set
        if 'language' not in conversation:
            conversation['language'] = 'en'

        user_message_lower = user_message.lower()

        # Detect explicit language switch requests
        kinyarwanda_triggers = [
            'use kinyarwanda', 'respond in kinyarwanda', 'please reply in kinyarwanda',
            'andika mu kinyarwanda', 'soma mu kinyarwanda', 'fasha mu kinyarwanda'
        ]
        english_triggers = [
            'switch to english', 'respond in english', 'please reply in english',
            'andika mu cyongereza', 'soma mu cyongereza'
        ]

        if any(phrase in user_message_lower for phrase in kinyarwanda_triggers):
            conversation['language'] = 'rw'
            logger.debug("Language switched to Kinyarwanda")
        elif any(phrase in user_message_lower for phrase in english_triggers):
            conversation['language'] = 'en'
            logger.debug("Language switched to English")

        # Append user message
        conversation['messages'].append({
            'sender': 'user',
            'content': user_message,
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_file': False
        })

        # Generate AI response
        if gemini_model:
            if conversation['language'] == 'rw':
                prompt = (
                    "Nyamuneka usubize mu Kinyarwanda kandi ukoreshe imiterere ya ChatGPT, "
                    "ugire code formatted neza, amafoto meza, n'amatebule ashobora gukopororwa. "
                    f"User: {user_message}\nAssistant:"
                )
            else:
                prompt = (
                    "Please respond in English with clear formatting like ChatGPT, "
                    "include code blocks for code, tables in copy-friendly format, and high quality images if needed. "
                    f"User: {user_message}\nAssistant:"
                )
            response = gemini_model.generate_content(prompt)
            ai_response = getattr(response, 'text', "⚠️ Could not generate a valid response.")
        else:
            ai_response = f"Echo: {user_message}"

        # Append AI response
        conversation['messages'].append({
            'sender': 'ai',
            'content': ai_response,
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_file': False
        })

        # Update conversation title if only default AI greeting and one user message exist
        if len(conversation['messages']) == 3:
            conversation['title'] = user_message[:20] + ("..." if len(user_message) > 20 else "")

        session.modified = True
        return jsonify({'success': True, 'response': ai_response, 'conversation': conversation})

    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    conv_id = request.form.get('conversation_id')

    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    conversation = next((c for c in session['conversations']['list'] if c['id'] == conv_id), None)
    if not conversation:
        return jsonify({'error': 'Conversation not found'}), 404

    try:
        # Avoid overwriting files by prefixing with UUID
        unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        conversation['file_info'] = {
            'filename': file.filename,
            'filepath': filepath,
            'uploaded_at': datetime.now().isoformat()
        }

        conversation['messages'].append({
            'sender': 'system',
            'content': f"📁 Upload yakozwe: {file.filename}",
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_file': True
        })

        # Try reading the file as CSV or Excel to analyze
        df = pd.DataFrame()
        try:
            if filepath.endswith('.csv'):
                df = pd.read_csv(filepath)
            elif filepath.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(filepath)
                df.dropna(how='all', inplace=True)
        except Exception as e:
            logger.error(f"Data load error: {str(e)}")

        if df.empty:
            analysis = "Fayile yoherejwe ariko ntibyashobotse gusesengura amakuru."
        else:
            analysis = f"Fayile yasomwe neza ifite imirongo {len(df)} n'inkingi {len(df.columns)}."

        conversation['messages'].append({
            'sender': 'ai',
            'content': analysis,
            'timestamp': datetime.now().strftime("%H:%M"),
            'is_file': False
        })

        session.modified = True
        return jsonify({'success': True, 'conversation': conversation})

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
