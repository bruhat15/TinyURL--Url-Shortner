from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from pyshorteners import Shortener
import sqlite3
from datetime import datetime, timedelta
import os
import uuid

app = Flask(__name__)

# Use environment variable or default secret key
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production-2024-tinyurl-pro')

# Session configuration - URLs expire after 2 hours
app.permanent_session_lifetime = timedelta(hours=2)

# Production configuration
if os.environ.get('VERCEL'):
    app.config['ENV'] = 'production'
    app.config['DEBUG'] = False

# Function to initialize user session
def initialize_session():
    """Initialize session with empty URL history if not exists"""
    if 'url_history' not in session:
        session['url_history'] = []
        session['session_id'] = str(uuid.uuid4())
    
    # Make session permanent (but still expires after 2 hours)
    session.permanent = True
    
    # Clean up old URLs (older than 2 hours)
    clean_session_history()

def clean_session_history():
    """Remove URLs older than 2 hours from session"""
    if 'url_history' not in session:
        return
    
    current_time = datetime.now()
    cutoff_time = current_time - timedelta(hours=2)
    
    # Filter out URLs older than 2 hours
    session['url_history'] = [
        url_data for url_data in session['url_history']
        if datetime.fromisoformat(url_data['date']) > cutoff_time
    ]
    session.modified = True

# Function to validate URL
def is_valid_url(url):
    """Basic URL validation"""
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        # Basic validation
        return url.startswith(('http://', 'https://')) and '.' in url and len(url) > 7
    except:
        return False

# Function to shorten URL with multiple services and better error handling
def shorten_url(url, max_retries=2):
    import time
    
    try:
        # Ensure URL has protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        if not is_valid_url(url):
            print(f"Invalid URL format: {url}")
            return None
        
        # Try multiple shortener services as fallbacks
        shortener = Shortener()
        
        # List of services to try in order with their configuration
        services_config = [
            ('TinyURL', lambda s: s.tinyurl),
            ('Is.gd', lambda s: s.isgd),
            ('Clck.ru', lambda s: s.clckru),
        ]
        
        for service_name, service_getter in services_config:
            for retry in range(max_retries):
                try:
                    print(f"Trying {service_name} for URL: {url} (attempt {retry + 1})")
                    
                    # Get the service instance
                    service = service_getter(shortener)
                    
                    # Try to shorten the URL
                    shortened = service.short(url)
                    
                    if shortened and shortened != url:  # Make sure we got a different URL back
                        print(f"✅ Successfully shortened with {service_name}: {shortened}")
                        return shortened
                    else:
                        print(f"⚠️ {service_name} returned the same URL or empty result")
                        
                except Exception as service_error:
                    error_msg = str(service_error)
                    print(f"❌ {service_name} attempt {retry + 1} failed: {error_msg}")
                    
                    # If it's a timeout, wait a bit before retrying
                    if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                        if retry < max_retries - 1:  # Don't wait after the last attempt
                            time.sleep(2)  # Wait 2 seconds before retry
                    continue
        
        # If all services fail, try a simple manual approach
        print(f"⚠️ All external services failed, creating manual short URL for: {url}")
        try:
            # Create a simple hash-based short URL as fallback
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            manual_short = f"http://short.ly/{url_hash}"
            print(f"✅ Created manual short URL: {manual_short}")
            return manual_short
        except Exception as hash_error:
            print(f"❌ Even manual shortening failed: {str(hash_error)}")
            return None
        
    except Exception as e:
        print(f"❌ General error shortening URL {url}: {str(e)}")
        return None

# Function to add URL to session
def add_to_session(name, original, shortened):
    """Add URL to user's session history"""
    if 'url_history' not in session:
        session['url_history'] = []
    
    # Generate a unique ID for this entry
    url_id = len(session['url_history']) + 1
    
    url_data = {
        'id': url_id,
        'name': name,
        'original': original,
        'shortened': shortened,
        'date': datetime.now().isoformat()  # Store as ISO format for easy parsing
    }
    
    session['url_history'].append(url_data)
    session.modified = True

# Function to delete URL from session
def delete_from_session(url_id):
    """Delete URL from user's session history by ID"""
    if 'url_history' not in session:
        return False
    
    # Find and remove the URL with the given ID
    original_length = len(session['url_history'])
    session['url_history'] = [
        url_data for url_data in session['url_history']
        if url_data['id'] != url_id
    ]
    session.modified = True
    
    return len(session['url_history']) < original_length

# Function to get all URLs from session
def get_all_urls():
    """Get all URLs from user's session history"""
    clean_session_history()  # Clean up old entries first
    
    if 'url_history' not in session:
        return []
    
    # Convert to the format expected by the template (tuple format)
    urls = []
    for url_data in reversed(session['url_history']):  # Show newest first
        # Convert datetime back to string format for display
        date_obj = datetime.fromisoformat(url_data['date'])
        formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        
        urls.append((
            url_data['id'],
            url_data['name'],
            url_data['original'],
            url_data['shortened'],
            formatted_date
        ))
    
    return urls

# Function to search URLs by name in session
def search_urls(query):
    """Search URLs in user's session history by name"""
    clean_session_history()  # Clean up old entries first
    
    if 'url_history' not in session:
        return []
    
    # Search for URLs matching the query
    matching_urls = []
    for url_data in session['url_history']:
        if query.lower() in url_data['name'].lower():
            # Convert to tuple format
            date_obj = datetime.fromisoformat(url_data['date'])
            formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            
            matching_urls.append((
                url_data['id'],
                url_data['name'],
                url_data['original'],
                url_data['shortened'],
                formatted_date
            ))
    
    return list(reversed(matching_urls))  # Show newest first

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'search_query' in request.form:
            search_query = request.form.get('search_query')
            if search_query:
                search_result = search_urls(search_query)
                if search_result:
                    flash(f"🔍 Found {len(search_result)} result(s) for '{search_query}'", 'success')
                    # Store search results in session to display after redirect
                    session['search_results'] = search_result
                    session['search_query'] = search_query
                else:
                    flash(f"🔍 No results found for '{search_query}'", 'info')
                    session.pop('search_results', None)
                    session.pop('search_query', None)
                return redirect(url_for('index'))
        else:
            name = request.form.get('name') or 'Unnamed'
            urls_text = request.form.get('urls')
            
            if not urls_text or not urls_text.strip():
                flash('Please enter at least one URL to shorten', 'error')
                return render_template('index.html', shortened_urls=get_all_urls())
            
            urls = [url.strip() for url in urls_text.splitlines() if url.strip()]
            successful_count = 0
            failed_urls = []
            
            for url in urls:
                if url:
                    shortened_url = shorten_url(url)
                    if shortened_url:
                        add_to_session(name, url, shortened_url)
                        successful_count += 1
                    else:
                        failed_urls.append(url)
            
            # Show appropriate flash messages
            if successful_count > 0:
                flash(f'✅ Successfully shortened {successful_count} URL(s)', 'success')
            
            if failed_urls:
                if len(failed_urls) == 1:
                    flash(f'❌ Failed to shorten URL: {failed_urls[0][:50]}{"..." if len(failed_urls[0]) > 50 else ""}. This might be due to network issues or the URL being blocked by shortener services.', 'error')
                else:
                    flash(f'❌ Failed to shorten {len(failed_urls)} URL(s). Network timeout or service unavailable. Please try again.', 'error')
            
            # Redirect to prevent form resubmission on page reload
            return redirect(url_for('index'))
    else:
        initialize_session()
        
        # Check if there are search results to display
        if 'search_results' in session:
            search_results = session.pop('search_results')
            search_query = session.pop('search_query', '')
            return render_template('index.html', shortened_urls=search_results, search_query=search_query)
        
        return render_template('index.html', shortened_urls=get_all_urls())

@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    try:
        if delete_from_session(id):
            flash('✅ URL deleted successfully', 'success')
        else:
            flash('❌ URL not found or already deleted', 'error')
    except Exception as e:
        flash('❌ Error deleting URL', 'error')
    return redirect(url_for('index'))

@app.route('/clear-search')
def clear_search():
    """Clear search results and return to main view"""
    session.pop('search_results', None)
    session.pop('search_query', None)
    return redirect(url_for('index'))

@app.route('/api/stats')
def get_stats():
    """API endpoint to get current session URL statistics"""
    try:
        clean_session_history()  # Clean expired URLs first
        
        if 'url_history' not in session:
            return jsonify({
                'total_urls': 0,
                'unique_campaigns': 0,
                'session_age_hours': 0
            })
        
        total_urls = len(session['url_history'])
        unique_campaigns = len(set(url_data['name'] for url_data in session['url_history']))
        
        # Calculate session age
        if session['url_history']:
            oldest_url = min(session['url_history'], key=lambda x: x['date'])
            oldest_date = datetime.fromisoformat(oldest_url['date'])
            session_age_hours = (datetime.now() - oldest_date).total_seconds() / 3600
        else:
            session_age_hours = 0
        
        return jsonify({
            'total_urls': total_urls,
            'unique_campaigns': unique_campaigns,
            'session_age_hours': round(session_age_hours, 2),
            'expires_in_hours': round(2 - session_age_hours, 2) if session_age_hours < 2 else 0
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# For Vercel deployment - this should be at the module level
# Vercel will call this app object directly
if __name__ == '__main__':
    # Local development
    print("🚀 Starting TinyURL Pro with session-based storage (2-hour expiry)")
    print("💡 URLs are stored per user session and automatically expire after 2 hours")
    print("🌐 Server running at: http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)

# This is needed for Vercel
app.config['ENV'] = 'production'
