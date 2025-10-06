import streamlit as st
from hybrid_engine import HybridEngine
from datetime import datetime
from pathlib import Path
import json
import os
import re
import time
import uuid
import random
import threading
import logging
from typing import List, Set
import sqlite3
import hashlib

# -----------------------------
# Setup & Configuration
# -----------------------------
st.set_page_config(
    page_title="TedPro Marketing Assistant 🧸",
    page_icon="🧸",
    layout="centered"
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"clients/tedpro_client/error.log"),
        logging.StreamHandler()
    ]
)

# -----------------------------
# Database Setup for Performance
# -----------------------------
def init_database():
    """Initialize SQLite database for better performance"""
    db_path = Path(f"clients/{client_id}/chat_data.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Conversations table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            session_id TEXT NOT NULL
        )
    ''')
    
    # Analytics table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analytics (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    ''')
    
    # Leads table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            context TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def append_to_conversation_db(role, content, session_id):
    """Append message to database (more efficient than JSON)"""
    try:
        db_path = Path(f"clients/{client_id}/chat_data.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO conversations (role, content, timestamp, session_id)
            VALUES (?, ?, ?, ?)
        ''', (role, content, datetime.now().isoformat(), session_id))
        
        # Keep only last 1000 messages per session for performance
        cursor.execute('''
            DELETE FROM conversations 
            WHERE id NOT IN (
                SELECT id FROM conversations 
                WHERE session_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1000
            )
        ''', (session_id,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Database error: {e}")

def load_recent_conversation_db(session_id, limit=50):
    """Load recent conversation from database"""
    try:
        db_path = Path(f"clients/{client_id}/chat_data.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT role, content, timestamp 
            FROM conversations 
            WHERE session_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (session_id, limit))
        
        messages = cursor.fetchall()
        conn.close()
        
        # Return in chronological order
        return [{"role": msg[0], "content": msg[1], "timestamp": msg[2]} for msg in reversed(messages)]
    except Exception as e:
        logging.error(f"Database load error: {e}")
        return []

# -----------------------------
# Core Functions
# -----------------------------
def get_key(name: str):
    return os.getenv(name) or st.secrets.get(name)

def extract_email(text: str):
    """Robust email validation using fullmatch"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    match = re.fullmatch(email_pattern, text.strip())
    return match.group(0) if match else None

def extract_name(text: str):
    """Simple name extraction - look for capitalized words that aren't email"""
    words = text.split()
    for word in words:
        if (word.istitle() and len(word) > 1 and 
            '@' not in word and '.' not in word and
            not any(char.isdigit() for char in word)):
            return word
    return "Friend"

def format_timestamp(timestamp_str):
    """More reliable timestamp formatting with better contrast"""
    try:
        if isinstance(timestamp_str, str):
            return datetime.fromisoformat(timestamp_str).strftime("%H:%M")
        else:
            return datetime.now().strftime("%H:%M")
    except (ValueError, TypeError):
        return datetime.now().strftime("%H:%M")

# Enhanced caching with better error handling
@st.cache_data(ttl=3600, show_spinner=False)
def cached_engine_answer(_engine, question: str) -> str:
    try:
        normalized = question.lower().strip()
        return _engine.answer(normalized)
    except Exception as e:
        logging.error(f"Engine error: {e}")
        return f"I'm having trouble right now. Please try again! 🧸"

def teddy_filter(user_message: str, raw_answer: str, is_first: bool, lead_captured: bool) -> str:
    friendly_prefix = "Hi there, friend! 🧸 " if is_first else ""
    sales_tail = ""
    
    if not lead_captured:
        if any(k in user_message.lower() for k in ["gift", "present", "birthday", "anniversary"]):
            sales_tail = " If this is a gift, I can suggest sizes or add a sweet note. 🎁"
        elif any(k in user_message.lower() for k in ["price", "how much", "cost", "buy"]):
            sales_tail = " I can also compare sizes to help you get the best value."
        elif any(k in user_message.lower() for k in ["custom", "personalize", "embroidery"]):
            sales_tail = " Tell me your idea—I'll check feasibility, timeline, and a fair quote."
    
    if any(k in user_message.lower() for k in ["buy", "order", "purchase"]):
        sales_tail += " 💳 You can place your order anytime at [Cuddleheroes Store](https://cuddleheroes.example.com)."
    
    return f"{friendly_prefix}{raw_answer}{sales_tail}"

# -----------------------------
# Performance-Optimized Analytics with Batch Support
# -----------------------------
_analytics_lock = threading.Lock()
_analytics_batch = {}

def get_analytics():
    """Get analytics from database"""
    default = {
        "total_messages": 0, "faq_questions": 0, "lead_captures": 0, 
        "sales_related": 0, "order_tracking": 0, "total_sessions": 0
    }
    try:
        db_path = Path(f"clients/{client_id}/chat_data.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT key, value FROM analytics')
        results = cursor.fetchall()
        conn.close()
        
        db_analytics = {row[0]: row[1] for row in results}
        return {**default, **db_analytics}
    except Exception as e:
        logging.error(f"Analytics load error: {e}")
        return default

def update_analytics_batch(updates, immediate=False):
    """Batch update analytics with optional immediate flush"""
    global _analytics_batch
    
    try:
        with _analytics_lock:
            # Merge updates into batch
            for key, increment in updates.items():
                _analytics_batch[key] = _analytics_batch.get(key, 0) + increment
            
            # Flush if immediate or batch is large
            if immediate or sum(_analytics_batch.values()) >= 10:
                if _analytics_batch:
                    db_path = Path(f"clients/{client_id}/chat_data.db")
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    
                    for key, increment in _analytics_batch.items():
                        cursor.execute('''
                            INSERT INTO analytics (key, value, updated_at) 
                            VALUES (?, ?, ?)
                            ON CONFLICT(key) DO UPDATE SET 
                            value = value + excluded.value,
                            updated_at = excluded.updated_at
                        ''', (key, increment, datetime.now().isoformat()))
                    
                    conn.commit()
                    conn.close()
                    
                    # Update session state
                    if "analytics" in st.session_state:
                        current = st.session_state.analytics
                        for key, increment in _analytics_batch.items():
                            current[key] = current.get(key, 0) + increment
                        st.session_state.analytics = current
                    
                    _analytics_batch = {}
                    
    except Exception as e:
        logging.error(f"Analytics update error: {e}")

# -----------------------------
# Engine Initialization
# -----------------------------
api_key = get_key("OPENROUTER_API_KEY")
if not api_key:
    st.error("🔑 Missing OPENROUTER_API_KEY. Set it in environment variables or Streamlit secrets.")
    st.stop()

client_id = "tedpro_client"

# Initialize database
init_database()

try:
    engine = HybridEngine(api_key=api_key, client_id=client_id)
except Exception as e:
    logging.error(f"Engine initialization failed: {e}")
    st.error(f"❌ Failed to initialize chatbot engine: {e}")
    st.stop()

# [Rest of your main.py content...]
# Note: The full main.py content would go here, but for brevity in this example,
# we're focusing on recreating the missing files
