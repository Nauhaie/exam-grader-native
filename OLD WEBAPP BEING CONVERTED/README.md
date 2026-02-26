# Exam Grader

A full-stack web application for grading scanned student exams. Upload PDFs, annotate them, enter grades in a spreadsheet interface, and export results.

## Prerequisites (macOS)

- **Homebrew**: Install from https://brew.sh
- **Python 3.11+**: `brew install python@3.11`
- **Node.js 18+**: `brew install node`
- **Git**: `brew install git` (usually pre-installed)

Verify versions:
```bash
python3 --version   # 3.11+
node --version      # 18+
npm --version
```

## Clone the Repository

```bash
git clone <repo-url>
cd exam-grader
```

## Docker Setup (Recommended)

If you have [Docker](https://docs.docker.com/get-docker/) and Docker Compose installed, you can run the entire app without installing Python or Node.js locally.

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Interactive API docs: http://localhost:8000/docs

> **Note:** The `backend/data/` directory is mounted as a volume, so your grades and annotations persist between container restarts. The `sample_data/` directory is also mounted so you can use the sample files immediately.

To stop the containers:

```bash
docker compose down
```

### Paths to use in Docker

When running via Docker, the backend runs inside a container where:
- The working directory is `/app`
- `./backend/data` on your Mac is mounted to `/app/data` in the container
- `./sample_data` on your Mac is mounted to `/app/sample_data` in the container

In the **Setup** form, enter **container paths** (not your Mac paths):

| Field | Docker path | What it maps to on your Mac |
|-------|-------------|------------------------------|
| Exams Directory | `/app/sample_data/exams` | `./sample_data/exams/` |
| Students CSV | `/app/sample_data/students.csv` | `./sample_data/students.csv` |
| Grading Scheme JSON | `/app/sample_data/grading_scheme.json` | `./sample_data/grading_scheme.json` |

### Using your own data with Docker

You have two options:

1. **Place your files in `sample_data/`** — the directory is already mounted, so files there are immediately available in the container.

2. **Add a custom volume mount** in `docker-compose.yml` to map any directory from your Mac into the container:

```yaml
    volumes:
      - ./backend/data:/app/data
      - ./sample_data:/app/sample_data
      - /Users/yourname/my-exams:/app/my-exams  # your custom data
```

Then use `/app/my-exams/...` as the path in the Setup form.

---

## Backend Setup

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the API server
uvicorn main:app --reload --port 8000
```

The backend will be available at http://localhost:8000.  
Interactive API docs: http://localhost:8000/docs

## Frontend Setup

Open a **new terminal** tab:

```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The frontend will be available at http://localhost:5173.

## Preparing Exam Files

1. Scan student exams and save each as a PDF.
2. Name each file using the student's number: `<student_number>.pdf`  
   Example: `12345.pdf`, `67890.pdf`
3. Place all PDF files in a single directory (e.g., `sample_data/exams/`).

## Accessing the App

1. Open http://localhost:5173 in your browser.
2. Fill in the **Setup** form with the paths to your files.

**Local (without Docker)** — use absolute Mac paths:
   - **Exams Directory**: `/Users/yourname/exam-grader/sample_data/exams`
   - **Students CSV**: `/Users/yourname/exam-grader/sample_data/students.csv`
   - **Grading Scheme JSON**: `/Users/yourname/exam-grader/sample_data/grading_scheme.json`

**Docker** — use container paths (the paths inside the container, not your Mac paths):
   - **Exams Directory**: `/app/sample_data/exams`
   - **Students CSV**: `/app/sample_data/students.csv`
   - **Grading Scheme JSON**: `/app/sample_data/grading_scheme.json`

3. Click **Start Grading**.

## Using Sample Data

The `sample_data/` directory contains example files to get you started:

| File | Description |
|------|-------------|
| `sample_data/students.csv` | 5 sample students |
| `sample_data/grading_scheme.json` | 2 exercises, 5 subquestions, 20 points total |
| `sample_data/exams/` | Place PDF files here (named `<student_number>.pdf`) |

### CSV Format

```csv
student_number,last_name,first_name
12345,Dupont,Jean
```

### Grading Scheme Format

```json
{
  "exercises": [
    {
      "name": "Exercise 1",
      "subquestions": [
        { "name": "1a", "max_points": 3 }
      ]
    }
  ]
}
```

## Features

- **PDF Viewer**: Navigate pages, zoom in/out
- **Annotations**: Add checkmarks, crosses, and text labels on PDF pages
- **Grading Spreadsheet**: Enter points per subquestion; auto-calculates totals and grades out of 20
- **Student Navigation**: Prev/Next buttons, search by name or student number
- **Export**: Download grades as CSV or XLSX; download original PDFs as a ZIP

## Grading

- Grades are calculated as: `(total_points / max_total_points) x 20`
- Grades are saved automatically (debounced 500ms) as you type
- Annotations are saved automatically when added or removed

## Export

- **CSV / XLSX**: All student grades in a tabular format
- **Annotated PDFs ZIP**: Original PDFs bundled into a ZIP archive

## Data Persistence

All data is stored in `backend/data/` as JSON files:
- `session_config.json` - current configuration
- `grades.json` - all entered grades
- `annotations/<student_number>.json` - per-student annotations

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Backend won't start | Ensure virtualenv is activated: `source venv/bin/activate` |
| Frontend can't reach API | Make sure backend is running on port 8000 |
| Docker: frontend can't reach API | Ensure you are using `docker compose up` (not running containers separately); the proxy uses the `backend` hostname |
| Docker: port already in use | Stop any local backend/frontend servers before running `docker compose up` |
| Docker: "file not found" in Setup form | Use container paths (e.g., `/app/sample_data/exams`), not your Mac paths. Make sure the directory is mounted in `docker-compose.yml`. |
| PDF not found error | Check that PDF file is named exactly `<student_number>.pdf` |
| CSV parse error | Ensure CSV has headers: `student_number,last_name,first_name` |
| Port already in use | Change port: `uvicorn main:app --port 8001` and update `vite.config.ts` |

## Architecture

- **Frontend**: React 18 + TypeScript + Vite
- **PDF Rendering**: react-pdf (pdf.js wrapper)
- **PDF Annotation**: pdf-lib (client-side)
- **Spreadsheet**: @tanstack/react-table
- **Backend**: Python FastAPI
- **Storage**: JSON files (no database required)
