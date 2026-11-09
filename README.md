# Career Transition Web App — “Смена профессии”

A web application that helps users explore adjacent career paths based on skills they already have. It aims to make career transitions more actionable by showing possible role matches, skill gaps and learning resources.

**Live demo:** https://smena-professii.onrender.com/

## The problem

People considering a career change may struggle to understand which of their current skills can transfer to another profession, what skills they are missing, and which learning resources are relevant to their next step.

## What the application does

- Matches a user's existing skills with related professions using a weighted scoring approach.
- Highlights skill gaps for a selected profession.
- Recommends relevant learning resources.
- Retrieves vacancy and salary-related information from external job-market services, where API access is available.
- Stores user-related application data in SQLite.

## Technology

- **Backend:** Python, FastAPI, Pydantic
- **Database:** SQLite
- **HTTP/API integration:** HTTPX, REST APIs, hh.ru and SuperJob
- **Frontend:** HTML5, CSS3, vanilla JavaScript
- **Deployment:** Render
- **Version control:** Git and GitHub

## Run locally

The commands below are a general setup outline. Check the repository's actual file names and configuration before using them.

```bash
git clone <PUBLIC_REPOSITORY_URL>
cd <REPOSITORY_DIRECTORY>
python -m venv .venv
```

Activate the virtual environment:

**Windows**
```powershell
.venv\Scripts\activate
```

**macOS / Linux**
```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Set any required API credentials as environment variables. Do not commit API keys or secrets to the repository.

Run the application using the command configured in the project. If `main.py` starts the FastAPI application directly, the command may be:

```bash
python main.py
```

Otherwise, use the start command documented in the repository.

## Project context

The project was developed as part of university coursework related to the software development life cycle. The work included defining the problem, considering user needs and existing solutions, implementing the application, integrating external services and deploying a working version.

## Future improvements

- Add secure user authentication and cloud-based profiles.
- Improve matching quality and explainability.
- Expand the learning-resource catalogue.
- Add automated tests and clearer usage analytics.

---

Developed by **Lev Smekalin**.
