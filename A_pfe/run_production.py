from waitress import serve
from main1 import app
import os
import sys
from datetime import datetime

def run_production_server():
    """
    Start production WSGI server
    """
    # Set production environment
    os.environ['FLASK_ENV'] = 'production'
    
    # Configuration
    HOST = '0.0.0.0'
    PORT = 5000
    THREADS = 4
    
    # Print startup info
    print("=" * 60)
    print("🚀 ERP API - Production Server")
    print("=" * 60)
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 Host: {HOST}")
    print(f"🔌 Port: {PORT}")
    print(f"🧵 Threads: {THREADS}")
    print("-" * 60)
    print("📍 Access URLs:")
    print(f"   • Local:   http://127.0.0.1:{PORT}")
    print(f"   • Network: http://192.168.8.6:{PORT}")
    print(f"   • Health:  http://127.0.0.1:{PORT}/health")
    print("-" * 60)
    print("⚙️  Scheduler: Running (updates every 2 minutes)")
    print("⚠️  Press CTRL+C to stop server")
    print("=" * 60)
    
    try:
        # Start Waitress server
        serve(
            app,
            host=HOST,
            port=PORT,
            threads=THREADS,
            url_scheme='http',
            channel_timeout=120,
            cleanup_interval=30,
            # Enable logging
            _quiet=False
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Server error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    run_production_server()