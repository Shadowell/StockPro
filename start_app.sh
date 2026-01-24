#!/bin/bash
cd "$(dirname "$0")"

# Start Backend
echo "Starting Backend..."
cd backend
# Check if venv exists, if not, create it
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Start FastAPI
# Use lsof to check if port 8000 is free, if not kill it
if lsof -t -i :8000 > /dev/null; then
    echo "Port 8000 is in use, killing process..."
    lsof -t -i :8000 | xargs kill -9
fi

uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Start Frontend
echo "Starting Frontend..."
cd frontend
# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo "Installing frontend dependencies..."
    npm install
fi

npm run dev &
FRONTEND_PID=$!
cd ..

# Set trap to kill processes on exit
trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

# Wait for servers to start
echo "Waiting for services to start..."
sleep 5

# Open Browser
echo "Opening Browser..."
open http://localhost:9999

echo "Application is running."
echo "Press CTRL+C to stop the servers..."

# Wait for processes
wait $BACKEND_PID $FRONTEND_PID
