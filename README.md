# ScoreCard Pro 🎓

A Flask-powered student scorecard generator. Upload a CSV + school logo → get beautiful, downloadable PDF scorecards.

## Project Structure

```
ScoreCardPro/
├── app.py               ← Flask backend (routes + PDF generation)
├── requirements.txt     ← Python dependencies
├── templates/
│   └── index.html       ← Frontend UI (served by Flask)
└── static/              ← Static assets (auto-created)
```

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python app.py

# 3. Open in browser
# http://localhost:5000
```

## How It Works

```
Browser uploads CSV + Logo
        ↓
POST /api/parse  →  Flask parses CSV, computes grades/ranks/averages
        ↓
JSON response    →  Browser renders live scorecard cards
        ↓
POST /api/pdf    →  Flask generates PDF with ReportLab
        ↓
PDF download     →  Browser triggers file save
```

## CSV Format

First column must be **Name**, all other columns are subject scores (assumed out of 100):

```
Name,Maths,Science,English,History
Alice,88,92,75,80
Bob,65,70,90,55
```

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET    | `/`          | Serve the frontend UI |
| POST   | `/api/parse` | Parse CSV → return JSON student data |
| POST   | `/api/pdf`   | Generate PDF → return file download |

### `/api/parse`
- Form field: `csv` (file)
- Returns: `{ students, subjects, summary }`

### `/api/pdf`
- Form fields: `students` (JSON), `subjects` (JSON), `org_name`, `target` (`all` or student name)
- Optional: `logo` (image file)
- Returns: PDF file attachment
