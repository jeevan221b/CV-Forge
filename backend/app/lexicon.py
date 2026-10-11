"""Technology/skill vocabulary and text helpers used by JD analysis, matching and fact checks.

The lexicon is intentionally a plain data table: add a line to teach the app a new term.
Terms outside the lexicon still work — users can add any keyword to a requirement and the
validator has a separate check for unfamiliar capitalised terms.
"""
from __future__ import annotations

import re
from functools import lru_cache

# canonical name -> aliases (matched case-insensitively unless listed in CASE_SENSITIVE)
LEXICON: dict[str, list[str]] = {
    # languages
    "Python": [], "JavaScript": ["JS", "ECMAScript"], "TypeScript": ["TS"], "Java": [], "C++": ["CPP"],
    "C#": ["CSharp"], "C": [], "Go": ["Golang"], "Rust": [], "Ruby": [], "PHP": [], "Swift": [],
    "Kotlin": [], "Scala": [], "R": [], "MATLAB": [], "SQL": [], "Bash": ["shell scripting", "shell scripts"],
    "PowerShell": [], "Perl": [], "Dart": [], "Elixir": [], "Haskell": [], "Lua": [], "Solidity": [],
    "HTML": ["HTML5"], "CSS": ["CSS3"], "Sass": ["SCSS"], "GraphQL": [], "LaTeX": [],
    # frontend
    "React": ["React.js", "ReactJS"], "Next.js": ["NextJS"], "Vue": ["Vue.js", "VueJS"], "Nuxt": ["Nuxt.js"],
    "Angular": ["AngularJS"], "Svelte": ["SvelteKit"], "Redux": [], "Tailwind CSS": ["Tailwind", "TailwindCSS"],
    "Bootstrap": [], "Vite": [], "Webpack": [], "jQuery": [], "React Native": [], "Flutter": [],
    "Storybook": [], "WebSockets": ["WebSocket"], "WebAssembly": ["WASM"],
    # backend
    "Node.js": ["Node", "NodeJS"], "Express": ["Express.js", "ExpressJS"], "NestJS": ["Nest.js"],
    "Django": [], "Flask": [], "FastAPI": [], "Spring Boot": ["Spring", "SpringBoot"],
    "Ruby on Rails": ["Rails"], "Laravel": [], ".NET": ["dotnet", "ASP.NET", ".NET Core"],
    "gRPC": [], "REST": ["RESTful", "REST API", "REST APIs", "RESTful APIs"], "microservices": ["microservice"],
    "OAuth": ["OAuth2", "OAuth 2.0"], "JWT": [], "Celery": [], "Pydantic": [], "SQLAlchemy": [],
    # data stores
    "PostgreSQL": ["Postgres"], "MySQL": [], "SQLite": [], "SQL Server": ["MSSQL"], "Oracle": [],
    "MongoDB": ["Mongo"], "Redis": [], "Elasticsearch": ["Elastic Search", "OpenSearch"], "DynamoDB": [],
    "Cassandra": [], "Snowflake": [], "BigQuery": [], "Redshift": [], "Neo4j": [], "Firebase": ["Firestore"],
    "Supabase": [], "NoSQL": [],
    # data / ml
    "Pandas": [], "NumPy": [], "scikit-learn": ["sklearn"], "PyTorch": [], "TensorFlow": [], "Keras": [],
    "Spark": ["PySpark", "Apache Spark"], "Hadoop": [], "Airflow": ["Apache Airflow"], "dbt": [],
    "Kafka": ["Apache Kafka"], "RabbitMQ": [], "Tableau": [], "Power BI": ["PowerBI"], "Looker": [],
    "Jupyter": [], "MLflow": [], "Hugging Face": ["HuggingFace"], "LangChain": [], "OpenCV": [],
    "machine learning": ["ML"], "deep learning": [], "NLP": ["natural language processing"],
    "LLM": ["LLMs", "large language models", "large language model"], "RAG": ["retrieval-augmented generation"],
    "computer vision": [], "data engineering": [], "ETL": ["ELT"], "data pipelines": ["data pipeline"],
    "statistics": ["statistical analysis"], "A/B testing": ["AB testing"],
    # cloud / devops
    "AWS": ["Amazon Web Services"], "GCP": ["Google Cloud", "Google Cloud Platform"], "Azure": ["Microsoft Azure"],
    "Docker": [], "Kubernetes": ["K8s"], "Terraform": [], "Ansible": [], "CloudFormation": [], "Helm": [],
    "Jenkins": [], "GitHub Actions": [], "GitLab CI": ["GitLab CI/CD"], "CircleCI": [], "ArgoCD": ["Argo CD"],
    "CI/CD": ["CICD", "continuous integration", "continuous delivery", "continuous deployment"],
    "Linux": ["Unix"], "Nginx": [], "Prometheus": [], "Grafana": [], "Datadog": [], "Sentry": [],
    "OpenTelemetry": [], "Lambda": ["AWS Lambda"], "S3": [], "EC2": [], "ECS": [], "EKS": [], "RDS": [],
    "serverless": [], "infrastructure as code": ["IaC"], "observability": [], "DevOps": [], "SRE": [],
    "cloud": ["cloud infrastructure", "cloud platforms", "cloud services"],
    "containers": ["containerization", "containerisation", "containerized"],
    # tooling / practice
    "Git": [], "GitHub": [], "GitLab": [], "Bitbucket": [], "Jira": [], "Confluence": [], "Figma": [],
    "pytest": [], "Jest": [], "JUnit": [], "Cypress": [], "Playwright": [], "Selenium": [],
    "unit testing": ["unit tests"], "integration testing": ["integration tests"], "TDD": ["test-driven development"],
    "automated testing": ["test automation"], "code review": ["code reviews"],
    "Agile": [], "Scrum": [], "Kanban": [], "system design": ["systems design"],
    "distributed systems": ["distributed system"], "API design": [], "data structures": [], "algorithms": [],
    "object-oriented programming": ["OOP", "object oriented"], "functional programming": [],
    "security": ["application security", "AppSec"], "accessibility": ["a11y", "WCAG"],
    "performance optimization": ["performance optimisation", "performance tuning"],
    "mentoring": ["mentorship"], "Excel": [], "SAP": [], "Salesforce": [],
}

# Matched with exact case so ordinary words ("go", "r", "c", "express") do not trigger them.
CASE_SENSITIVE = {"Go", "R", "C", "Express", "Spark", "Rust", "Swift", "Oracle", "Helm", "Lambda", "Jest",
                  "Sass", "Dart", "Flask", "Looker", "Sentry", "Rails", "Spring", "Node", "Elixir", "Perl",
                  "Vue", "Nuxt", "Vite", "Git", "Excel", "Agile", "TS", "JS", "ML", "RAG", "SRE", "ETL",
                  "ELT", "S3", "Mongo", "Angular", "Bootstrap", "React", "Celery", "Ruby", "Azure", "SAP"}

# concept -> concrete terms. A requirement naming one side and evidence naming the other is
# reported as "indirect", never as explicit support.
RELATED: dict[str, list[str]] = {
    "CI/CD": ["GitHub Actions", "GitLab CI", "Jenkins", "CircleCI", "ArgoCD"],
    "cloud": ["AWS", "GCP", "Azure", "Lambda", "S3", "EC2", "ECS", "EKS", "RDS"],
    "AWS": ["Lambda", "S3", "EC2", "ECS", "EKS", "RDS", "DynamoDB", "CloudFormation", "Redshift"],
    "GCP": ["BigQuery", "Firebase"],
    "SQL": ["PostgreSQL", "MySQL", "SQLite", "SQL Server", "Oracle", "Snowflake", "BigQuery", "Redshift"],
    "NoSQL": ["MongoDB", "Redis", "DynamoDB", "Cassandra", "Firebase"],
    "containers": ["Docker", "Kubernetes", "Helm", "ECS", "EKS"],
    "infrastructure as code": ["Terraform", "Ansible", "CloudFormation", "Helm"],
    "machine learning": ["PyTorch", "TensorFlow", "scikit-learn", "Keras", "MLflow", "deep learning"],
    "deep learning": ["PyTorch", "TensorFlow", "Keras"],
    "LLM": ["LangChain", "Hugging Face", "RAG"],
    "automated testing": ["pytest", "Jest", "JUnit", "Cypress", "Playwright", "Selenium", "unit testing",
                          "integration testing", "TDD"],
    "unit testing": ["pytest", "Jest", "JUnit"],
    "REST": ["FastAPI", "Flask", "Django", "Express", "Spring Boot", "NestJS", "Ruby on Rails", "API design"],
    "microservices": ["gRPC", "Kafka", "RabbitMQ", "Kubernetes"],
    "data pipelines": ["Airflow", "Spark", "dbt", "Kafka", "ETL"],
    "data engineering": ["Airflow", "Spark", "dbt", "Kafka", "ETL", "Snowflake"],
    "observability": ["Prometheus", "Grafana", "Datadog", "Sentry", "OpenTelemetry"],
    "Agile": ["Scrum", "Kanban", "Jira"],
    "JavaScript": ["TypeScript", "React", "Node.js", "Vue", "Angular"],
    "React": ["Next.js", "Redux", "React Native"],
    "Vue": ["Nuxt"],
    "Git": ["GitHub", "GitLab", "Bitbucket"],
    "Linux": ["Bash"],
    "Python": ["Django", "Flask", "FastAPI", "Pandas", "NumPy", "pytest"],
    "Java": ["Spring Boot", "JUnit"],
    "DevOps": ["CI/CD", "Docker", "Kubernetes", "Terraform"],
}

_EDGE_L = r"(?<![A-Za-z0-9])"
_EDGE_R = r"(?![A-Za-z0-9])"


def _one(form: str, case_sensitive: bool) -> str:
    pat = re.escape(form).replace(r"\ ", r"[\s\-]+")
    tail = _EDGE_R
    if form in {"C", "R"}:
        tail = r"(?![A-Za-z0-9+#&/.])"  # not C++, C#, R&D
    elif not form[-1].isalnum():
        tail = ""
    head = _EDGE_L if form[0].isalnum() else r"(?<![A-Za-z0-9.])"
    body = pat if case_sensitive else f"(?i:{pat})"
    return f"{head}{body}{tail}"


@lru_cache(maxsize=None)
def term_pattern(term: str) -> re.Pattern[str]:
    """Regex for a canonical lexicon term (with aliases) or any free-form keyword."""
    canonical = canonical_term(term)
    if canonical in LEXICON:
        forms = [canonical, *LEXICON[canonical]]
        return re.compile("|".join(_one(f, f in CASE_SENSITIVE) for f in forms))
    return re.compile(_one(term.strip(), False))


@lru_cache(maxsize=None)
def _lookup() -> dict[str, str]:
    table: dict[str, str] = {}
    for canonical, aliases in LEXICON.items():
        for form in (canonical, *aliases):
            table[form.lower()] = canonical
    return table


def canonical_term(term: str) -> str:
    return _lookup().get(term.strip().lower(), term.strip())


def term_in_text(term: str, text: str) -> bool:
    return bool(term and term.strip() and term_pattern(term).search(text))


def find_terms(text: str) -> list[str]:
    """Canonical lexicon terms present in `text`, in order of first appearance."""
    hits: list[tuple[int, str]] = []
    for canonical in LEXICON:
        m = term_pattern(canonical).search(text)
        if m:
            hits.append((m.start(), canonical))
    return [t for _, t in sorted(hits)]


def related_terms(term: str) -> set[str]:
    """Concrete technologies that fall under a broader term (CI/CD -> GitHub Actions, ...).

    Deliberately one-directional: doing "CI/CD" work with GitHub Actions is indirect evidence for a
    CI/CD requirement, but having built "data pipelines" says nothing about knowing Kafka.
    """
    canonical = canonical_term(term)
    return set(RELATED.get(canonical, [])) - {canonical}


STOPWORDS = frozenset("""
a an the and or of to in on for with by at from as is are be been being will would can could should may
might must have has had do does did this that these those you your our we us they their it its not no nor
other such than then into over under about across within without via per etc including include includes
ability able strong excellent good great solid proven demonstrated experience experienced years year plus
knowledge understanding familiarity familiar working work works proficiency proficient skills skill using use
used well role team teams new high highly least minimum preferred required requirement requirements
qualifications qualification nice bonus ideal ideally who what when where which while also both either
more most some any all each every own one two three four five six seven eight nine ten related relevant
equivalent degree field similar various multiple environment environments looking seeking candidate job
position company help make ensure need needs needed like want based day part time full
""".split())

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")


def stem(word: str) -> str:
    w = word.lower().strip(".-/")
    for suffix, minimum in (("ization", 5), ("isation", 5), ("ations", 4), ("ation", 4), ("ments", 4),
                            ("ment", 4), ("ing", 4), ("ies", 3), ("ed", 4), ("es", 4), ("s", 4)):
        if w.endswith(suffix) and len(w) - len(suffix) >= minimum - 1:
            w = w[: -len(suffix)]
            break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def content_stems(text: str) -> set[str]:
    return {stem(w) for w in _WORD_RE.findall(text) if len(w) > 2 and w.lower() not in STOPWORDS}


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
