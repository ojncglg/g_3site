"""
G3 Industries public website backend.

This module handles:
1) Page rendering routes.
2) Public demo-form intake and anti-abuse controls.
3) Email delivery through Resend or SMTP.
4) Baseline security headers and HTTPS redirect behavior.

The goal is to keep this file readable for non-specialists who need to
understand operational behavior quickly.
"""

# Standard library imports used for persistence, validation, and delivery.
import csv
import hashlib
import hmac
import io
import json
import os
import re
import smtplib
import ssl
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, List
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from xml.sax.saxutils import escape as xml_escape

# Flask objects used by routes/middleware.
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

# Create the Flask application instance.
app = Flask(__name__)

# Secret key powers session signing and flash-message integrity.
# In production this must be injected via env var.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")

# Reject unexpectedly large requests early (default 64 KB).
# This prevents oversized payload abuse against public form endpoints.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_FORM_CONTENT_BYTES", "65536"))

# Decide whether service is running as a production deployment.
RUNNING_PRODUCTION = os.environ.get("RENDER", "").lower() == "true" or os.environ.get(
    "FLASK_ENV", ""
).lower() == "production"
# Hard-fail startup in production if default key is still present.
if RUNNING_PRODUCTION and app.config["SECRET_KEY"] == "dev-change-me":
    raise RuntimeError("SECRET_KEY must be set in production.")

# Shared contact addresses consumed by templates and email handlers.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "grigori.lopezgarcia@g3industries.io")
DEMO_TO_EMAIL = os.environ.get("DEMO_TO_EMAIL", CONTACT_EMAIL)
DEMO_FROM_EMAIL = os.environ.get("DEMO_FROM_EMAIL", DEMO_TO_EMAIL)

# Analytics settings (GA4 recommended for this site).
ANALYTICS_PROVIDER = os.environ.get("ANALYTICS_PROVIDER", "").strip().lower()
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()
CLARITY_PROJECT_ID = os.environ.get("CLARITY_PROJECT_ID", "").strip()
SITE_PUBLISHED_LABEL = os.environ.get("SITE_PUBLISHED_LABEL", "March 2026").strip()
SITE_LAST_UPDATED_LABEL = os.environ.get(
    "SITE_LAST_UPDATED_LABEL", "March 29, 2026"
).strip()
INDEXNOW_KEY = os.environ.get("INDEXNOW_KEY", "").strip()

# Cloudflare Turnstile settings (optional anti-bot challenge).
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
TURNSTILE_VERIFY_URL = os.environ.get(
    "TURNSTILE_VERIFY_URL",
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
).strip()

# Basic-auth credentials for the internal leads dashboard.
ADMIN_DASHBOARD_USERNAME = os.environ.get("ADMIN_DASHBOARD_USERNAME", "admin").strip()
ADMIN_DASHBOARD_PASSWORD = os.environ.get("ADMIN_DASHBOARD_PASSWORD", "").strip()

# SMTP settings used when provider is "smtp" or when "auto" falls back to SMTP.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get(
    "SMTP_USERNAME",
    os.environ.get("SMTP_USER", CONTACT_EMAIL),
).strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", ""))
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip() in ("1", "true", "True")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0").strip() in ("1", "true", "True")
SMTP_TIMEOUT_SECONDS = float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
# In production this should stay enabled; set to 0 temporarily if you're testing locally.
REQUIRE_EMAIL_DELIVERY = os.environ.get("REQUIRE_EMAIL_DELIVERY", "1").strip() in (
    "1",
    "true",
    "True",
)
# Outbound provider selection:
# - "auto": prefer Resend when configured; otherwise use SMTP.
# - "resend": only use Resend API.
# - "smtp": only use SMTP.
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", DEMO_FROM_EMAIL).strip()
RESEND_API_URL = os.environ.get("RESEND_API_URL", "https://api.resend.com/emails").strip()

# Field-length controls used during form validation.
FIELD_MAX_LENGTHS = {
    "name": 120,
    "agency": 160,
    "role": 120,
    "email": 254,
    "phone": 40,
    "notes": 2000,
    "utm_source": 120,
    "utm_medium": 120,
    "utm_campaign": 160,
    "utm_term": 160,
    "utm_content": 160,
    "landing_page": 2048,
    "referrer": 2048,
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+().\-\s]{7,40}$")

# Salt used to hash identity keys inside the local rate-limit store.
RATE_LIMIT_SALT = os.environ.get("RATE_LIMIT_SALT", app.config["SECRET_KEY"])

# Per-network throttling controls.
DEMO_IP_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_IP_LIMIT_WINDOW_SECONDS", "300"))
DEMO_IP_LIMIT_COUNT = int(os.environ.get("DEMO_IP_LIMIT_COUNT", "5"))

# Per-email throttling controls.
DEMO_EMAIL_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_EMAIL_LIMIT_WINDOW_SECONDS", "1800"))
DEMO_EMAIL_LIMIT_COUNT = int(os.environ.get("DEMO_EMAIL_LIMIT_COUNT", "3"))

# Global endpoint burst controls.
DEMO_GLOBAL_LIMIT_WINDOW_SECONDS = int(os.environ.get("DEMO_GLOBAL_LIMIT_WINDOW_SECONDS", "60"))
DEMO_GLOBAL_LIMIT_COUNT = int(os.environ.get("DEMO_GLOBAL_LIMIT_COUNT", "25"))

# Minimum seconds between two requests from same IP.
DEMO_IP_MIN_INTERVAL_SECONDS = int(os.environ.get("DEMO_IP_MIN_INTERVAL_SECONDS", "10"))

# Filesystem paths used by simple on-disk storage.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LEADS_FILE = os.path.join(DATA_DIR, "leads.json")
RATE_LIMIT_FILE = os.path.join(DATA_DIR, "rate_limits.json")

# Seed blog content lives in code for now so publishing is simple.
# Each post appears at /blog/<slug>.
BLOG_POSTS: List[Dict[str, Any]] = [
    {
        "slug": "why-change-is-so-hard-in-policing",
        "title": "Why Change Is So Hard in Policing",
        "description": (
            "Law enforcement is built on reliability and mission-first execution, but that "
            "same culture can make administrative modernization difficult."
        ),
        "published_at": "2026-03-29",
        "published_label": "March 29, 2026",
        "updated_at": "2026-03-29",
        "updated_label": "March 29, 2026",
        "read_time": "4 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Police Operations", "Change Management", "Administrative Systems"],
        "summary": (
            "Policing consistently gets the mission done, but legacy administrative systems "
            "can hold agencies back from operating at their full potential."
        ),
        "quick_answer": (
            "Change is hard in policing because reliability-focused culture keeps missions "
            "moving, but it can also preserve inefficient admin workflows longer than needed."
        ),
        "key_takeaways": [
            "Mission-first culture is a core strength in policing, but it can also slow operational modernization.",
            "Most police technologies faced early resistance before proving safety, accountability, and efficiency gains.",
            "Administrative inefficiency directly affects field performance by consuming command and officer time.",
            "The best software adapts to agency workflows instead of forcing agencies to relearn how they work.",
        ],
        "qa": [
            {
                "question": "Why is change in policing often slower than expected?",
                "answer": (
                    "Because agencies prioritize reliability and continuity, proven workflows are often "
                    "protected even when they are no longer efficient."
                ),
            },
            {
                "question": "Where are the biggest modernization opportunities right now?",
                "answer": (
                    "In administrative systems like scheduling, approvals, reporting, and data management, "
                    "where many departments still rely on fragmented processes."
                ),
            },
            {
                "question": "What makes law enforcement software successful in real agencies?",
                "answer": (
                    "It aligns to real policy and rank structure, reduces friction, and improves visibility "
                    "without disrupting mission-critical operations."
                ),
            },
        ],
        "sections": [
            {
                "heading": "A Culture Built on Reliability",
                "paragraphs": [
                    "If you have spent any time in law enforcement, you have probably heard the phrase: 'we have always done it this way.' It is more than a saying - it reflects a culture built on consistency, reliability, and mission-first execution. In policing, the job has to get done regardless of the tools available, and officers have always found a way to make it work.",
                    "That mindset is one of the profession's greatest strengths. It keeps operations moving under any condition. But it also creates resistance to change. When a process works, even if it is inefficient, it becomes the standard. Over time, that standard becomes difficult to challenge.",
                ],
                "bullets": [],
            },
            {
                "heading": "Technology Pushback Is Nothing New",
                "paragraphs": [
                    "Historically, nearly every major advancement in police technology has faced pushback. In-car computers, dash cameras, body-worn cameras, tasers, and modern police software systems were all met with skepticism when first introduced. Concerns ranged from trust in the technology to disruption of established workflows. Yet over time, these tools proved their value by improving officer safety, increasing accountability, and streamlining operations. Today, they are no longer optional - they are expected.",
                ],
                "bullets": [],
            },
            {
                "heading": "The Hidden Cost of Stability",
                "paragraphs": [
                    "The challenge is not just the technology itself, but the environment it enters. Law enforcement agencies often prioritize stability over innovation, which is understandable given the high-stakes nature of the work. However, when stability turns into rigidity, progress slows. The 'make it work' mentality ensures continuity, but it can also keep outdated administrative systems in place long after better solutions exist.",
                    "This is where the real cost appears. Manual processes, paper-based workflows, and disconnected systems still exist in many departments. These inefficiencies do not just create inconvenience - they consume valuable time, reduce visibility, and pull officers and command staff away from higher-priority responsibilities. In modern policing, administrative inefficiency directly impacts operational performance.",
                ],
                "bullets": [],
            },
            {
                "heading": "The Administrative Gap",
                "paragraphs": [
                    "From my experience, some of the biggest opportunities for improvement are not in the field, but behind the scenes. While operational technology in law enforcement continues to advance, administrative technology often lags behind. Scheduling, reporting, approvals, and data management are still frequently handled through outdated or fragmented systems. When these systems are misaligned, agencies are forced to operate at a high level while compensating for avoidable inefficiencies.",
                ],
                "bullets": [],
            },
            {
                "heading": "What Effective Change Looks Like",
                "paragraphs": [
                    "This is the gap many agencies are now beginning to address. The goal is not to introduce change for the sake of change, but to implement systems that align with real-world police workflows and reduce unnecessary friction. The most effective law enforcement software does not force agencies to adapt to it - it adapts to how agencies already operate while improving efficiency and visibility.",
                ],
                "bullets": [],
            },
            {
                "heading": "The Real Question for Agencies",
                "paragraphs": [
                    "Policing will always accomplish the mission. That has never been the question. The real question is whether agencies are willing to improve how that mission is carried out. Change in law enforcement is difficult, but when implemented correctly, it strengthens operations, supports officers, and enhances the overall effectiveness of the department.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Modernize without disrupting operations",
        "cta_body": (
            "If your team is balancing mission-critical work with outdated admin processes, "
            "we can map practical improvements that fit how your agency already operates."
        ),
    },
    {
        "slug": "5-signs-your-police-scheduling-process-is-breaking-at-scale",
        "title": "5 Signs Your Police Scheduling Process Is Breaking at Scale",
        "description": (
            "A practical checklist for command staff to spot when police scheduling and "
            "approval workflows are no longer keeping up with operational demand."
        ),
        "published_at": "2026-03-28",
        "published_label": "March 28, 2026",
        "updated_at": "2026-03-28",
        "updated_label": "March 28, 2026",
        "read_time": "5 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Scheduling", "Command Staff", "Police Operations"],
        "summary": (
            "If approvals lag, staffing visibility drops, and officers rely on side-channel "
            "messages, your scheduling process is likely under strain."
        ),
        "quick_answer": (
            "When your schedule depends on texts, spreadsheets, and manual reconciliation, "
            "you lose visibility fast as staffing volume grows."
        ),
        "key_takeaways": [
            "Delayed approvals create avoidable staffing risk before each shift starts.",
            "Disconnected tools increase duplicate work for supervisors and command staff.",
            "Side-channel coordination hides decision history and weakens accountability.",
            "One policy-aligned scheduling workflow restores visibility at scale.",
        ],
        "qa": [
            {
                "question": "What is the first warning sign?",
                "answer": (
                    "Approval turnaround times start drifting from same-shift decisions into "
                    "multi-day delays."
                ),
            },
            {
                "question": "Why does side-channel communication hurt scheduling quality?",
                "answer": (
                    "Because key decisions move into texts and emails that are hard to verify, "
                    "search, or audit later."
                ),
            },
            {
                "question": "What should command teams track immediately?",
                "answer": (
                    "Track approval cycle time, low-staff incident frequency, and how often "
                    "supervisors manually reconcile the same request data."
                ),
            },
        ],
        "sections": [
            {
                "heading": "What breaking at scale looks like",
                "paragraphs": [
                    "Most scheduling processes work fine when volume is light. Problems appear when requests, shift moves, and policy constraints increase at the same time.",
                    "If supervisors are chasing the same information across paper, text messages, and spreadsheets, your process is already absorbing hidden operational cost.",
                ],
                "bullets": [],
            },
            {
                "heading": "The 5 warning signs",
                "paragraphs": [
                    "Watch for these patterns: approvals lagging into the next day, frequent last-minute staffing surprises, duplicate data entry by supervisors, unresolved schedule disputes, and missing audit context during reviews.",
                ],
                "bullets": [
                    "Approvals shift from same-shift to multi-day response",
                    "Coverage risk is discovered late instead of early",
                    "Supervisors re-enter the same request in multiple places",
                    "Disputes increase because decision history is fragmented",
                    "Audit prep requires manual reconstruction of events",
                ],
            },
            {
                "heading": "How to stabilize before it gets worse",
                "paragraphs": [
                    "Standardize one request and approval path, enforce policy checks in that workflow, and keep one source of truth for command visibility.",
                    "You do not need to replace everything at once. Start with the scheduling bottleneck that costs your team the most time each week.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Want a fast scheduling health check?",
        "cta_body": (
            "We can map your current scheduling workflow and identify where command-level "
            "time and visibility are being lost first."
        ),
    },
    {
        "slug": "why-vacation-approval-delays-hurt-staffing-readiness",
        "title": "Why Vacation Approval Delays Hurt Staffing Readiness",
        "description": (
            "How approval lag in vacation requests creates preventable staffing blind spots "
            "for supervisors and command staff."
        ),
        "published_at": "2026-03-27",
        "published_label": "March 27, 2026",
        "updated_at": "2026-03-27",
        "updated_label": "March 27, 2026",
        "read_time": "4 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Vacation Workflow", "Staffing Readiness", "Supervisors"],
        "summary": (
            "When approval decisions are delayed, readiness decisions are delayed. That gap "
            "creates avoidable pressure on supervisors before each shift."
        ),
        "quick_answer": (
            "Vacation approval lag is not just admin delay; it is staffing risk delay."
        ),
        "key_takeaways": [
            "Approval speed directly affects confidence in staffing decisions.",
            "Policy checks should happen during approval, not after the fact.",
            "Visibility gaps force supervisors into reactive coverage moves.",
            "A single workflow reduces handoff friction between ranks.",
        ],
        "qa": [
            {
                "question": "Why is delayed approval a command problem?",
                "answer": (
                    "Because command needs timely staffing truth to assign resources and avoid "
                    "last-minute shortfalls."
                ),
            },
            {
                "question": "Where do delays usually happen?",
                "answer": (
                    "In handoffs between request intake, supervisor review, and policy validation "
                    "when those steps happen in different tools."
                ),
            },
            {
                "question": "What is the fastest practical fix?",
                "answer": (
                    "Use one approval queue with visible staffing impact and policy guardrails so "
                    "decisions are made once and shared instantly."
                ),
            },
        ],
        "sections": [
            {
                "heading": "Approval lag becomes readiness lag",
                "paragraphs": [
                    "Every pending vacation request represents uncertainty in your staffing plan. When approvals sit, that uncertainty rolls into shift-level decisions.",
                    "Supervisors then make coverage decisions with partial information, which increases rework and escalations.",
                ],
                "bullets": [],
            },
            {
                "heading": "Common delay points",
                "paragraphs": [
                    "Requests often move through text, email, and paper before landing in the scheduling system. Each handoff adds delay and risk.",
                ],
                "bullets": [
                    "No single queue for pending approvals",
                    "Policy checks happen after a decision, not during it",
                    "Staffing impact is not visible until late",
                ],
            },
            {
                "heading": "What better looks like",
                "paragraphs": [
                    "A supervisor should see request details, policy guardrails, and staffing impact in one place, then approve or deny once.",
                    "That single action should update command visibility immediately so readiness decisions stay current.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Need to tighten approval turnaround?",
        "cta_body": (
            "We can help your agency reduce approval friction while preserving policy control "
            "and command visibility."
        ),
    },
    {
        "slug": "fixing-extra-duty-assignment-friction-before-it-becomes-overtime",
        "title": "Fixing Extra-Duty Assignment Friction Before It Becomes Overtime",
        "description": (
            "A practical look at where extra-duty workflows break down and how agencies can "
            "reduce assignment delays, disputes, and overtime spillover."
        ),
        "published_at": "2026-03-26",
        "published_label": "March 26, 2026",
        "updated_at": "2026-03-26",
        "updated_label": "March 26, 2026",
        "read_time": "5 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Extra Duty", "Assignment Fairness", "Operations"],
        "summary": (
            "When intake, vetting, and assignment logic are fragmented, extra-duty requests "
            "slow down and workload pressure shifts back into normal staffing."
        ),
        "quick_answer": (
            "Extra-duty friction becomes overtime pressure when assignment decisions are slow, "
            "unclear, or inconsistent."
        ),
        "key_takeaways": [
            "Assignment speed and assignment trust are both operational requirements.",
            "Manual coordination increases dispute frequency and review overhead.",
            "Clear assignment rules reduce escalation load on supervisors.",
            "Audit-ready records protect both officers and leadership decisions.",
        ],
        "qa": [
            {
                "question": "What usually creates assignment disputes?",
                "answer": (
                    "Inconsistent application of assignment rules and poor visibility into how "
                    "decisions were made."
                ),
            },
            {
                "question": "How does this affect normal staffing?",
                "answer": (
                    "When extra-duty coverage is unresolved late, supervisors compensate by "
                    "reallocating attention and time from core operations."
                ),
            },
            {
                "question": "What should be standardized first?",
                "answer": (
                    "Standardize intake requirements, eligibility checks, and assignment logic "
                    "in one process."
                ),
            },
        ],
        "sections": [
            {
                "heading": "Where extra-duty workflows lose time",
                "paragraphs": [
                    "Extra-duty coordination often starts outside the system, then gets pushed into manual review later.",
                    "That delay creates friction for supervisors and uncertainty for officers waiting on assignment outcomes.",
                ],
                "bullets": [],
            },
            {
                "heading": "What command should watch",
                "paragraphs": [
                    "If the same request is being touched repeatedly by different people, your workflow is absorbing avoidable cost.",
                ],
                "bullets": [
                    "Late assignment confirmation",
                    "Frequent exception handling",
                    "Disputes with incomplete decision history",
                ],
            },
            {
                "heading": "How to reduce friction without adding complexity",
                "paragraphs": [
                    "Capture requests in one intake path, apply clear eligibility rules, and keep assignment outcomes visible to all relevant roles.",
                    "When rules are transparent and consistently applied, assignment confidence improves quickly.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Want cleaner extra-duty operations?",
        "cta_body": (
            "We can help you standardize assignment flow so supervisors spend less time "
            "managing exceptions and more time supporting operations."
        ),
    },
    {
        "slug": "tow-logs-and-audit-risk-what-command-staff-should-standardize-first",
        "title": "Tow Logs and Audit Risk: What Command Staff Should Standardize First",
        "description": (
            "Tow logging is often treated as simple data entry, but inconsistent records can "
            "create major audit and accountability risk."
        ),
        "published_at": "2026-03-25",
        "published_label": "March 25, 2026",
        "updated_at": "2026-03-25",
        "updated_label": "March 25, 2026",
        "read_time": "4 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Tow Logs", "Audit Readiness", "Accountability"],
        "summary": (
            "Tow workflows need consistent entry standards and clear custody history. Without "
            "that, command teams lose confidence in record quality."
        ),
        "quick_answer": (
            "Tow log inconsistency is an audit risk multiplier, especially when history has to "
            "be reconstructed after the fact."
        ),
        "key_takeaways": [
            "Required fields and custody events need consistent enforcement.",
            "Searchability is as important as initial record capture.",
            "Export quality determines how fast audits can be completed.",
            "Standardized tow logging reduces review friction across units.",
        ],
        "qa": [
            {
                "question": "Why do tow logs fail audits?",
                "answer": (
                    "Records are often incomplete, inconsistent, or disconnected from custody "
                    "history timelines."
                ),
            },
            {
                "question": "What does command need from tow data?",
                "answer": (
                    "Reliable search, clean exports, and confidence that each record follows "
                    "policy from entry to closure."
                ),
            },
            {
                "question": "What should be standardized first?",
                "answer": (
                    "Start with mandatory entry fields, custody event tracking, and one export "
                    "format that supports reviews."
                ),
            },
        ],
        "sections": [
            {
                "heading": "Tow logs are accountability records",
                "paragraphs": [
                    "Tow entries are not just administrative paperwork. They are operational records that may be reviewed long after the event.",
                    "If fields are inconsistent, leadership spends audit time reconstructing basic context instead of validating decisions.",
                ],
                "bullets": [],
            },
            {
                "heading": "Where quality usually breaks",
                "paragraphs": [
                    "Most breakdowns happen at handoff points: entry, custody updates, and export formatting for review.",
                ],
                "bullets": [
                    "Missing required fields",
                    "Unclear custody status timeline",
                    "Inconsistent export output by unit",
                ],
            },
            {
                "heading": "Command-first standardization",
                "paragraphs": [
                    "Build one tow logging path with required validation and searchable history, then keep export output consistent for audits and records requests.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Need cleaner tow-log accountability?",
        "cta_body": (
            "We can help standardize tow records so your team can review and export with "
            "confidence instead of manual cleanup."
        ),
    },
    {
        "slug": "anonymous-tips-intake-how-to-improve-follow-through-without-slowing-investigations",
        "title": "Anonymous Tips Intake: How to Improve Follow-Through Without Slowing Investigations",
        "description": (
            "How agencies can tighten anonymous tips intake, triage, and follow-through while "
            "keeping response workflows practical for supervisors."
        ),
        "published_at": "2026-03-24",
        "published_label": "March 24, 2026",
        "updated_at": "2026-03-24",
        "updated_label": "March 24, 2026",
        "read_time": "4 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Anonymous Tips", "Triage", "Workflow Design"],
        "summary": (
            "Tip intake quality matters. If routing and follow-through are inconsistent, useful "
            "information gets buried or delayed."
        ),
        "quick_answer": (
            "Anonymous tip workflows work best when intake fields, triage rules, and follow-up "
            "ownership are clear from the start."
        ),
        "key_takeaways": [
            "Intake quality determines triage quality.",
            "Tip routing should be structured, not ad hoc.",
            "Ownership and status tracking prevent tip drift.",
            "Supervisors need visibility without extra admin burden.",
        ],
        "qa": [
            {
                "question": "What is the most common intake failure?",
                "answer": (
                    "Insufficient structure during intake, which forces supervisors to spend "
                    "time clarifying basic context before action."
                ),
            },
            {
                "question": "How do agencies avoid losing tips in process?",
                "answer": (
                    "Assign ownership, track status transitions, and keep a visible queue for "
                    "pending and closed items."
                ),
            },
            {
                "question": "Can this be improved without adding bureaucracy?",
                "answer": (
                    "Yes. Standardized intake and lightweight triage rules improve consistency "
                    "without slowing response."
                ),
            },
        ],
        "sections": [
            {
                "heading": "Good intake prevents downstream friction",
                "paragraphs": [
                    "When intake is inconsistent, triage becomes guesswork. That slows response and makes status tracking harder than it needs to be.",
                    "A better intake model captures the right context early so supervisors can route quickly.",
                ],
                "bullets": [],
            },
            {
                "heading": "Triage needs clear ownership",
                "paragraphs": [
                    "Without ownership, tips can sit in queue and lose urgency. Ownership does not need to be complex, but it must be explicit.",
                ],
                "bullets": [
                    "Clear assignment by role",
                    "Status checkpoints from intake to closure",
                    "Supervisor visibility on pending backlog",
                ],
            },
            {
                "heading": "Keep it practical for the field",
                "paragraphs": [
                    "The goal is not paperwork. The goal is faster, clearer follow-through with less ambiguity for everyone involved.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Want tighter tip follow-through?",
        "cta_body": (
            "We can help your team standardize intake and triage so supervisors keep visibility "
            "without adding unnecessary process."
        ),
    },
    {
        "slug": "policy-guardrails-vs-workarounds-where-agencies-lose-visibility",
        "title": "Policy Guardrails vs Workarounds: Where Agencies Lose Visibility",
        "description": (
            "Why policy-compliant workflows matter for command visibility and how workaround "
            "culture creates blind spots in daily operations."
        ),
        "published_at": "2026-03-23",
        "published_label": "March 23, 2026",
        "updated_at": "2026-03-23",
        "updated_label": "March 23, 2026",
        "read_time": "5 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Policy Compliance", "Visibility", "Command Staff"],
        "summary": (
            "Workarounds can keep operations moving in the short term, but over time they "
            "reduce visibility and make policy enforcement harder."
        ),
        "quick_answer": (
            "If your workflow depends on exceptions and side channels, command loses clear "
            "visibility into how decisions are actually made."
        ),
        "key_takeaways": [
            "Workarounds are signals that policy and workflow are misaligned.",
            "Command visibility drops when decisions leave the core system.",
            "Guardrails should support operations, not block them.",
            "Operational trust improves when policy logic is transparent in workflow.",
        ],
        "qa": [
            {
                "question": "Why do workarounds become normal?",
                "answer": (
                    "Because teams prioritize mission continuity and adopt whatever path resolves "
                    "the immediate bottleneck."
                ),
            },
            {
                "question": "What is the risk to leadership?",
                "answer": (
                    "Leadership loses reliable, system-level visibility and has to reconstruct "
                    "decision context during reviews."
                ),
            },
            {
                "question": "What is a healthier approach?",
                "answer": (
                    "Align policy guardrails directly with day-to-day workflows so compliance and "
                    "operations reinforce each other."
                ),
            },
        ],
        "sections": [
            {
                "heading": "Why workaround culture persists",
                "paragraphs": [
                    "In policing, teams solve problems quickly. When tools do not align with real work, informal paths emerge to keep the mission moving.",
                    "The problem is not intent. The problem is that those paths are harder to track, review, and improve.",
                ],
                "bullets": [],
            },
            {
                "heading": "Where visibility breaks first",
                "paragraphs": [
                    "Visibility usually breaks at points where policy decisions and operational actions are recorded in different places.",
                ],
                "bullets": [
                    "Approval decisions outside the system",
                    "Exceptions tracked manually by supervisors",
                    "Inconsistent records across units and shifts",
                ],
            },
            {
                "heading": "Build guardrails people will actually use",
                "paragraphs": [
                    "The best guardrails are embedded in the workflow officers and supervisors already use.",
                    "When policy logic is clear inside the process, adoption improves and command visibility stays intact.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Need stronger visibility without more friction?",
        "cta_body": (
            "We can help map where workarounds are hiding and rebuild those steps into "
            "policy-aligned workflows your team can use every day."
        ),
    },
    {
        "slug": "how-much-time-are-administrative-tasks-worth",
        "title": "How Much Time Are Administrative Tasks Worth?",
        "description": (
            "As a chief or decision-maker, ask what repetitive administrative work is costing "
            "your agency in command-level time each month."
        ),
        "published_at": "2026-03-18",
        "published_label": "March 18, 2026",
        "updated_at": "2026-03-18",
        "updated_label": "March 18, 2026",
        "read_time": "5 min read",
        "author_name": "Grigori LopezGarcia",
        "author_role": "Founder, G3 Industries",
        "tags": ["Command Staff", "Administrative Workflows", "Police Operations"],
        "summary": (
            "As a chief or decision-maker, ask yourself how much time your squad commanders "
            "spend on repetitive administrative tasks and what that is costing your department."
        ),
        "quick_answer": (
            "Administrative work quietly consumes command-level hours every month, and that time "
            "loss is expensive for agencies trying to keep staffing coverage strong."
        ),
        "key_takeaways": [
            "Even conservative estimates show administrative work can consume dozens of command-level hours each month.",
            "High-value leaders often spend significant time reconciling requests across disconnected tools.",
            "Automating repetitive workflows improves visibility and returns time to operational priorities.",
            "Small process improvements at the command level scale quickly across all shifts.",
        ],
        "qa": [
            {
                "question": "Why does administrative workflow matter so much for command staff?",
                "answer": (
                    "Because it directly impacts how much time supervisors can spend on planning, "
                    "staffing readiness, and field support instead of manual reconciliation."
                ),
            },
            {
                "question": "What is the cost of disconnected tools like paper, text, and email?",
                "answer": (
                    "They create duplicate work, increase error risk, and pull high-paid command "
                    "personnel into repetitive tasks that software should handle."
                ),
            },
            {
                "question": "What improves first when workflows are automated?",
                "answer": (
                    "Approval speed, staffing visibility, and auditability usually improve first, while "
                    "command teams recover time for higher-priority responsibilities."
                ),
            },
        ],
        "sections": [
            {
                "heading": "How much time are administrative tasks worth?",
                "paragraphs": [
                    "As a chief or a decision-maker, ask yourself: how much time are my squad commanders spending on repetitive administrative tasks, and how much is that costing the department?",
                    "Say you run an agency with 100 officers and your squad commander is in charge of about 15 officers. That commander has to reconcile text messages, emails, and paper vacation slips into one document and upload it.",
                    "Then they still have to update old HR software and code vacation time, plus activity sheets, into a system built for general government work, not police work.",
                ],
                "bullets": [],
            },
            {
                "heading": "Run the math on command-level time",
                "paragraphs": [
                    "How long does that take? Three to four hours every week? Let us be conservative and call it two hours every week.",
                    "That is around eight hours every month for one squad commander, and this is usually one of your highest-paid officers.",
                    "Now consider four squads for 24/7 coverage. You are spending around 32 hours every month from high-income earners on repetitive administrative tasks. Is that worth it?",
                ],
                "bullets": [
                    "2 hours/week x 4 weeks = 8 hours/month per squad commander",
                    "8 hours x 4 squads = 32 command-level hours/month",
                ],
            },
            {
                "heading": "Change is hard, but time is still your most expensive resource",
                "paragraphs": [
                    "I will be the first one to admit that cops do not like change. Sometimes we can be very stubborn when it comes to adopting new technology.",
                    "But what if there was a solution that automated this process?",
                    "That would free up squad commanders, provide command staff clear visibility on deployment across your beats, and let officers focus on serving the community instead of admin tasks.",
                    "This is why we created our platform.",
                ],
                "bullets": [],
            },
            {
                "heading": "If this sounds familiar",
                "paragraphs": [
                    "If you have a similar problem, send us an email and we can provide a demo of our software to see if we are the right fit.",
                ],
                "bullets": [],
            },
        ],
        "cta_title": "Want to see if this fits your agency?",
        "cta_body": (
            "If this challenge sounds familiar, we can walk you through a quick demo and map "
            "where your command team can recover time first."
        ),
    }
]
BLOG_POSTS_BY_SLUG: Dict[str, Dict[str, Any]] = {post["slug"]: post for post in BLOG_POSTS}
BLOG_SLUG_REDIRECTS: Dict[str, str] = {
    "5-police-workflows-that-waste-time": "how-much-time-are-administrative-tasks-worth"
}

# Centralized CSP applied to responses unless explicitly overridden.
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://www.googletagmanager.com https://www.clarity.ms https://*.clarity.ms https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: https://www.google-analytics.com https://www.clarity.ms https://*.clarity.ms https://challenges.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "connect-src 'self' https://www.google-analytics.com https://www.googletagmanager.com https://www.clarity.ms https://*.clarity.ms https://challenges.cloudflare.com; "
    "frame-src 'self' https://challenges.cloudflare.com; "
    "base-uri 'self'; "
    "form-action 'self' mailto:; "
    "frame-ancestors 'none'"
)

# Trust one proxy hop so Flask receives real client protocol/IP data.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def utc_now_ms() -> int:
    """Return current UTC time in milliseconds for anti-spam timing checks."""
    return int(utc_now().timestamp() * 1000)


def wants_json_response() -> bool:
    """Detect whether caller expects JSON (AJAX/fetch/API style requests)."""
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
    )


def redirect_to_demo_anchor():
    """Send browser users back to the home page demo section."""
    return redirect(url_for("home", _anchor="demo"))


def ensure_data_store() -> None:
    """Create local lead storage if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "w", encoding="utf-8") as file:
            json.dump([], file)
    if not os.path.exists(RATE_LIMIT_FILE):
        with open(RATE_LIMIT_FILE, "w", encoding="utf-8") as file:
            json.dump({"global": [], "ip": {}, "email": {}}, file)


def append_lead(lead: Dict[str, Any]) -> None:
    """Append one lead object to leads.json while tolerating a corrupt file."""
    ensure_data_store()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as file:
            data: List[Dict[str, Any]] = json.load(file)
    except json.JSONDecodeError:
        data = []

    data.append(lead)
    with open(LEADS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_leads() -> List[Dict[str, Any]]:
    """Load all leads from disk safely."""
    ensure_data_store()
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as file:
            loaded = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(loaded, list):
        return []
    return [row for row in loaded if isinstance(row, dict)]


def parse_lead_timestamp(value: str) -> datetime | None:
    """Parse stored lead timestamps as UTC datetimes."""
    if not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def safe_lead_bucket(value: str, fallback: str = "(direct/unknown)") -> str:
    """Normalize attribution labels for grouped reporting."""
    normalized = normalize_text(value).lower()
    return normalized or fallback


def preview_text(value: str, limit: int = 90) -> str:
    """Create a short preview snippet for table views."""
    value = normalize_text(value, allow_newlines=True)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def published_blog_posts() -> List[Dict[str, Any]]:
    """Return blog posts sorted by publish date (newest first)."""
    return sorted(BLOG_POSTS, key=lambda post: post.get("published_at", ""), reverse=True)


def build_lead_dashboard_data(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build aggregate report data for the admin leads dashboard."""
    now_utc = utc_now()
    cutoff_30d = now_utc - timedelta(days=30)
    parsed_rows = []
    source_counts: Counter[str] = Counter()
    campaign_counts: Counter[str] = Counter()
    day_counts: Counter[str] = Counter()
    leads_last_30_days = 0

    for lead in leads:
        timestamp_raw = normalize_text(lead.get("timestamp", ""))
        timestamp_dt = parse_lead_timestamp(timestamp_raw)
        timestamp_label = (
            timestamp_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            if timestamp_dt
            else (timestamp_raw or "(unknown)")
        )

        source = safe_lead_bucket(lead.get("utm_source", ""))
        campaign = safe_lead_bucket(lead.get("utm_campaign", ""), "(none)")

        source_counts[source] += 1
        campaign_counts[campaign] += 1
        if timestamp_dt:
            day_counts[timestamp_dt.strftime("%Y-%m-%d")] += 1
            if timestamp_dt >= cutoff_30d:
                leads_last_30_days += 1

        parsed_rows.append(
            {
                "timestamp_raw": timestamp_raw,
                "timestamp_dt": timestamp_dt,
                "timestamp_label": timestamp_label,
                "name": normalize_text(lead.get("name", "")),
                "agency": normalize_text(lead.get("agency", "")),
                "role": normalize_text(lead.get("role", "")),
                "email": normalize_text(lead.get("email", "")),
                "phone": normalize_text(lead.get("phone", "")),
                "utm_source": source,
                "utm_medium": safe_lead_bucket(lead.get("utm_medium", ""), "(none)"),
                "utm_campaign": campaign,
                "landing_page": normalize_text(lead.get("landing_page", "")),
                "referrer": normalize_text(lead.get("referrer", "")),
                "notes_preview": preview_text(lead.get("notes", "")),
            }
        )

    parsed_rows.sort(
        key=lambda row: (
            row["timestamp_dt"] is not None,
            row["timestamp_dt"] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    recent_day_counts = sorted(day_counts.items(), reverse=True)[:14]
    recent_day_counts.reverse()

    return {
        "total_leads": len(parsed_rows),
        "leads_last_30_days": leads_last_30_days,
        "top_sources": source_counts.most_common(8),
        "top_campaigns": campaign_counts.most_common(8),
        "leads_by_day": recent_day_counts,
        "recent_leads": parsed_rows[:200],
    }


def admin_dashboard_enabled() -> bool:
    """Return whether the internal dashboard is enabled."""
    return bool(ADMIN_DASHBOARD_PASSWORD)


def admin_unauthorized_response() -> Response:
    """Return a standard basic-auth challenge response."""
    return Response(
        "Authentication required.",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="G3 Admin Leads", charset="UTF-8"'},
    )


def require_admin_auth() -> Response | None:
    """Enforce basic auth for internal dashboard routes."""
    if not admin_dashboard_enabled():
        abort(404)

    auth = request.authorization
    if not auth or (auth.type or "").lower() != "basic":
        return admin_unauthorized_response()

    provided_user = auth.username or ""
    provided_password = auth.password or ""
    username_ok = hmac.compare_digest(provided_user, ADMIN_DASHBOARD_USERNAME)
    password_ok = hmac.compare_digest(provided_password, ADMIN_DASHBOARD_PASSWORD)
    if not (username_ok and password_ok):
        return admin_unauthorized_response()

    return None


def normalize_text(value: str, *, allow_newlines: bool = False) -> str:
    """Trim and normalize user-provided text for consistent validation."""
    value = (value or "").replace("\x00", "").strip()
    if allow_newlines:
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(value.split())


def clip_text(value: str, max_length: int) -> str:
    """Clip untrusted text to a safe max length."""
    return value[:max_length] if len(value) > max_length else value


def get_client_ip() -> str:
    """
    Resolve the best-available client IP.
    ProxyFix already handles trusted proxy headers, but Cloudflare and some edges
    still provide explicit headers we can prefer.
    """
    cloudflare_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cloudflare_ip:
        return cloudflare_ip
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.remote_addr or "unknown"


def stable_rate_key(value: str) -> str:
    """Hash identifiers before storing in rate-limit state."""
    digest = hashlib.sha256(f"{RATE_LIMIT_SALT}|{value}".encode("utf-8")).hexdigest()
    return digest[:32]


def load_rate_store() -> Dict[str, Any]:
    """Load rate-limit state from disk with a safe fallback."""
    ensure_data_store()
    try:
        with open(RATE_LIMIT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}

    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("global"), list):
        data["global"] = []
    if not isinstance(data.get("ip"), dict):
        data["ip"] = {}
    if not isinstance(data.get("email"), dict):
        data["email"] = {}
    return data


def save_rate_store(data: Dict[str, Any]) -> None:
    """Persist rate-limit state atomically."""
    ensure_data_store()
    temp_file = RATE_LIMIT_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)
    os.replace(temp_file, RATE_LIMIT_FILE)


def prune_recent(events: List[int], now_s: int, window_s: int) -> List[int]:
    """Keep only event timestamps inside the configured time window."""
    cutoff = now_s - window_s
    return [timestamp for timestamp in events if timestamp >= cutoff]


def check_and_record_rate_limit(client_ip: str, email: str) -> tuple[bool, str]:
    """
    Enforce burst and windowed limits to prevent form abuse.
    Limits:
    - global requests per minute
    - per-IP requests per 5 minutes + minimum interval between requests
    - per-email requests per 30 minutes
    """
    now_s = int(utc_now().timestamp())
    state = load_rate_store()

    global_events = prune_recent(
        [int(value) for value in state["global"] if isinstance(value, int)],
        now_s,
        DEMO_GLOBAL_LIMIT_WINDOW_SECONDS,
    )
    if len(global_events) >= DEMO_GLOBAL_LIMIT_COUNT:
        return False, "Too many requests right now. Please wait a minute and try again."

    ip_key = stable_rate_key(client_ip)
    ip_events = prune_recent(
        [int(value) for value in state["ip"].get(ip_key, []) if isinstance(value, int)],
        now_s,
        DEMO_IP_LIMIT_WINDOW_SECONDS,
    )
    if ip_events and (now_s - ip_events[-1]) < DEMO_IP_MIN_INTERVAL_SECONDS:
        return False, "Please wait a few seconds before submitting again."
    if len(ip_events) >= DEMO_IP_LIMIT_COUNT:
        return False, "Too many requests from this network. Please try again later."

    email_key = stable_rate_key(email.lower())
    email_events = prune_recent(
        [int(value) for value in state["email"].get(email_key, []) if isinstance(value, int)],
        now_s,
        DEMO_EMAIL_LIMIT_WINDOW_SECONDS,
    )
    if len(email_events) >= DEMO_EMAIL_LIMIT_COUNT:
        return False, "Too many demo requests for this email. Please try again later."

    global_events.append(now_s)
    ip_events.append(now_s)
    email_events.append(now_s)

    state["global"] = global_events
    state["ip"][ip_key] = ip_events
    state["email"][email_key] = email_events
    save_rate_store(state)
    return True, ""


def verify_turnstile_token(token: str, client_ip: str) -> tuple[bool, str]:
    """
    Verify Cloudflare Turnstile token when anti-bot mode is enabled.
    Returns (ok, error_message).
    """
    # If Turnstile is not configured, skip verification.
    if not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY:
        return True, ""

    if not token:
        return False, "Please complete the verification challenge."

    payload = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }
    if client_ip and client_ip != "unknown":
        payload["remoteip"] = client_ip

    data = urllib_parse.urlencode(payload).encode("utf-8")
    req = urllib_request.Request(
        TURNSTILE_VERIFY_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "g3-industries-site/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=SMTP_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
    except Exception as exc:  # pylint: disable=broad-except
        app.logger.warning("Turnstile verification request failed: %s", exc)
        return False, "Verification failed. Please try again."

    if parsed.get("success") is True:
        return True, ""

    error_codes = parsed.get("error-codes", [])
    app.logger.warning("Turnstile verification rejected: %s", error_codes)
    return False, "Verification failed. Please retry and submit again."


def send_demo_email(lead: Dict[str, Any]) -> tuple[bool, str]:
    """
    Send a demo request email through the configured provider.
    Returns (ok, error_message).
    """
    subject = f"New Demo Request — {lead.get('agency', 'Unknown Agency')}"
    body_lines = [
        "A new demo request was submitted on g3industries.io.",
        "",
        f"Name: {lead.get('name', '')}",
        f"Agency: {lead.get('agency', '')}",
        f"Role/Rank: {lead.get('role', '')}",
        f"Email: {lead.get('email', '')}",
        f"Phone: {lead.get('phone', '')}",
        "",
        "Notes:",
        lead.get("notes", "") or "(none)",
        "",
        "Metadata:",
        f"Submitted At (UTC): {lead.get('timestamp', '')}",
        f"Source IP: {lead.get('source_ip', '')}",
        f"User Agent: {lead.get('user_agent', '')}",
        f"Elapsed MS: {lead.get('elapsed_ms', '')}",
        "",
        "Attribution:",
        f"UTM Source: {lead.get('utm_source', '') or '(none)'}",
        f"UTM Medium: {lead.get('utm_medium', '') or '(none)'}",
        f"UTM Campaign: {lead.get('utm_campaign', '') or '(none)'}",
        f"UTM Term: {lead.get('utm_term', '') or '(none)'}",
        f"UTM Content: {lead.get('utm_content', '') or '(none)'}",
        f"Landing Page: {lead.get('landing_page', '') or '(unknown)'}",
        f"Referrer: {lead.get('referrer', '') or '(none)'}",
    ]
    body_text = "\n".join(body_lines)

    # Provider routing:
    # 1) Use Resend first when allowed and configured.
    # 2) If provider is strictly "resend", return Resend error directly.
    # 3) Otherwise fall back to SMTP.
    if EMAIL_PROVIDER in ("auto", "resend") and RESEND_API_KEY:
        ok, message = send_demo_email_resend(subject, body_text, lead)
        if ok:
            return True, ""
        if EMAIL_PROVIDER == "resend":
            return False, message

    if EMAIL_PROVIDER == "resend" and not RESEND_API_KEY:
        return False, "RESEND_API_KEY is missing while EMAIL_PROVIDER=resend."

    # Fallback path for smtp/auto mode.
    return send_demo_email_smtp(subject, body_text, lead)


def send_demo_email_resend(subject: str, body_text: str, lead: Dict[str, Any]) -> tuple[bool, str]:
    """Send demo request email through the Resend API."""
    # Build JSON payload expected by Resend.
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [DEMO_TO_EMAIL],
        "subject": subject,
        "text": body_text,
        # Keep threaded replies pointed to the requestor.
        "reply_to": lead.get("email", DEMO_TO_EMAIL),
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        RESEND_API_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            # Resend requires a User-Agent for direct HTTP requests.
            "User-Agent": "g3-industries-site/1.0",
            "Accept": "application/json",
        },
    )
    try:
        # Execute HTTPS request to Resend API.
        with urllib_request.urlopen(req, timeout=SMTP_TIMEOUT_SECONDS) as response:
            if 200 <= response.status < 300:
                return True, ""
            return False, f"Resend API returned status {response.status}."
    except urllib_error.HTTPError as exc:
        # Return server-provided response body for debugging.
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"Resend API HTTP {exc.code}: {body}"
    except Exception as exc:  # pylint: disable=broad-except
        return False, f"Resend API error: {exc}"


def send_demo_email_smtp(subject: str, body_text: str, lead: Dict[str, Any]) -> tuple[bool, str]:
    """Send demo request email through SMTP."""
    if not SMTP_HOST:
        message = "SMTP is not configured (missing SMTP_HOST)."
        if app.debug and not REQUIRE_EMAIL_DELIVERY:
            # Allow local development without a configured mail server.
            app.logger.warning(message)
            return True, ""
        return False, message

    if not SMTP_PASSWORD:
        return False, "SMTP password is missing (set SMTP_PASSWORD)."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = DEMO_FROM_EMAIL
    message["To"] = DEMO_TO_EMAIL
    message["Reply-To"] = lead.get("email", DEMO_TO_EMAIL)
    message.set_content(body_text)

    try:
        # SSL mode uses implicit TLS on connect.
        if SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                SMTP_HOST,
                SMTP_PORT,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=context,
            ) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
        else:
            # Plain socket mode can upgrade with STARTTLS.
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
                if SMTP_USE_TLS:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
    except Exception as exc:  # pylint: disable=broad-except
        return False, str(exc)

    return True, ""


@app.context_processor
def inject_contact_email():
    """Expose common template values (contact + analytics settings)."""
    return {
        "contact_email": CONTACT_EMAIL,
        "analytics_provider": ANALYTICS_PROVIDER,
        "ga_measurement_id": GA_MEASUREMENT_ID,
        "clarity_project_id": CLARITY_PROJECT_ID,
        "turnstile_site_key": TURNSTILE_SITE_KEY,
        "site_published_label": SITE_PUBLISHED_LABEL,
        "site_last_updated_label": SITE_LAST_UPDATED_LABEL,
    }


@app.before_request
def enforce_https():
    """Redirect plaintext GET/HEAD requests to HTTPS in non-debug mode."""
    # Only redirect safe idempotent methods.
    if request.method not in ("GET", "HEAD"):
        return None
    if app.debug or request.is_secure:
        return None
    # Convert explicit http:// URLs to https://.
    if request.url.startswith("http://"):
        return redirect(request.url.replace("http://", "https://", 1), code=301)
    return None


@app.after_request
def set_security_headers(response):
    """Attach baseline security headers to every response."""
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), geolocation=(), microphone=()"
    )
    response.headers.setdefault("Content-Security-Policy", DEFAULT_CSP)
    return response


@app.errorhandler(413)
def request_too_large(_error):
    """Handle oversized form submissions without exposing internals."""
    if wants_json_response():
        return jsonify({"ok": False, "error": "Submission too large."}), 413
    flash("Submission too large. Please shorten your message and try again.", "error")
    return redirect_to_demo_anchor()


@app.route("/_health")
def health():
    """Lightweight health endpoint for deploy checks."""
    return "ok", 200


@app.route("/indexnow-key.txt")
def indexnow_key_txt():
    """Expose IndexNow verification key when configured."""
    if not INDEXNOW_KEY:
        abort(404)
    return Response(INDEXNOW_KEY, mimetype="text/plain")


@app.route("/")
def home():
    """Marketing home page."""
    return render_template("index.html", title="G3 Industries")


@app.route("/products")
def products():
    """Products overview page."""
    return render_template("products.html", title="Products — G3 Industries")


@app.route("/impact")
def impact():
    """Impact Program page."""
    return render_template("impact.html", title="IMPACT Program — G3 Industries")


@app.route("/about")
def about():
    """Company/about page."""
    return render_template("about.html", title="About — G3 Industries")


@app.route("/security")
def security():
    """Security posture page."""
    return render_template("security.html", title="Security — G3 Industries")


@app.route("/grants")
def grants():
    """Grant assistance page."""
    return render_template("grants.html", title="Grant Assistance — G3 Industries")


@app.route("/blog")
def blog():
    """Blog index page."""
    return render_template(
        "blog.html",
        title="Blog — G3 Industries",
        posts=published_blog_posts(),
    )


@app.route("/blog/<slug>")
def blog_post(slug: str):
    """Individual blog article page."""
    post = BLOG_POSTS_BY_SLUG.get(slug)
    if not post:
        redirect_slug = BLOG_SLUG_REDIRECTS.get(slug)
        if redirect_slug:
            return redirect(url_for("blog_post", slug=redirect_slug), code=301)
        abort(404)
    return render_template(
        "blog_post.html",
        title=f"{post['title']} — G3 Industries",
        post=post,
    )


@app.route("/admin/leads")
def admin_leads():
    """Internal dashboard showing lead volume and attribution breakdowns."""
    auth_error = require_admin_auth()
    if auth_error:
        return auth_error

    leads = load_leads()
    dashboard_data = build_lead_dashboard_data(leads)
    return render_template(
        "admin_leads.html",
        title="Leads Dashboard — G3 Industries",
        dashboard=dashboard_data,
    )


@app.route("/admin/leads.csv")
def admin_leads_csv():
    """Export leads as CSV for offline analysis."""
    auth_error = require_admin_auth()
    if auth_error:
        return auth_error

    leads = load_leads()
    dashboard_data = build_lead_dashboard_data(leads)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "timestamp_utc",
            "name",
            "agency",
            "role",
            "email",
            "phone",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "landing_page",
            "referrer",
        ]
    )
    for lead in dashboard_data["recent_leads"]:
        writer.writerow(
            [
                lead.get("timestamp_label", ""),
                lead.get("name", ""),
                lead.get("agency", ""),
                lead.get("role", ""),
                lead.get("email", ""),
                lead.get("phone", ""),
                lead.get("utm_source", ""),
                lead.get("utm_medium", ""),
                lead.get("utm_campaign", ""),
                lead.get("landing_page", ""),
                lead.get("referrer", ""),
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="g3-leads-export.csv"',
            "Cache-Control": "no-store",
        },
    )


@app.route("/demo", methods=["POST"])
def demo():
    """
    Handle demo-request submissions:
    - normalize input
    - apply anti-spam checks
    - validate required fields
    - persist lead
    - return JSON for fetch clients or redirect+flash for browsers
    """
    # Read and normalize user input values.
    name = normalize_text(request.form.get("name", ""))
    agency = normalize_text(request.form.get("agency", ""))
    role = normalize_text(request.form.get("role", ""))
    email = normalize_text(request.form.get("email", "")).lower()
    phone = normalize_text(request.form.get("phone", ""))
    notes = normalize_text(request.form.get("notes", ""), allow_newlines=True)
    utm_source = normalize_text(request.form.get("utm_source", ""))
    utm_medium = normalize_text(request.form.get("utm_medium", ""))
    utm_campaign = normalize_text(request.form.get("utm_campaign", ""))
    utm_term = normalize_text(request.form.get("utm_term", ""))
    utm_content = normalize_text(request.form.get("utm_content", ""))
    landing_page = normalize_text(request.form.get("landing_page", ""))
    referrer = normalize_text(request.form.get("referrer", ""))
    turnstile_token = normalize_text(request.form.get("cf-turnstile-response", ""))
    honeypot = normalize_text(request.form.get("website", ""))
    form_start = normalize_text(request.form.get("form_start", ""))
    client_ip = get_client_ip()

    # Time-based anti-spam check: require ~3 seconds before submit.
    min_delay_ms = 3000
    elapsed_ms = None
    elapsed_ok = True
    if form_start:
        try:
            elapsed_ms = max(0, utc_now_ms() - int(form_start))
            elapsed_ok = elapsed_ms >= min_delay_ms
        except ValueError:
            # Keep this permissive so malformed input does not block humans.
            elapsed_ok = True

    # Honeypot trips are treated as bot submissions and quietly ignored.
    if honeypot:
        if wants_json_response():
            return jsonify({"ok": True, "message": "Thanks"}), 200
        flash("Thanks — we’ll be in touch.", "success")
        return redirect_to_demo_anchor()

    # Trim optional attribution metadata to fixed safe limits.
    utm_source = clip_text(utm_source, FIELD_MAX_LENGTHS["utm_source"])
    utm_medium = clip_text(utm_medium, FIELD_MAX_LENGTHS["utm_medium"])
    utm_campaign = clip_text(utm_campaign, FIELD_MAX_LENGTHS["utm_campaign"])
    utm_term = clip_text(utm_term, FIELD_MAX_LENGTHS["utm_term"])
    utm_content = clip_text(utm_content, FIELD_MAX_LENGTHS["utm_content"])
    landing_page = clip_text(landing_page, FIELD_MAX_LENGTHS["landing_page"])
    referrer = clip_text(
        referrer or normalize_text(request.referrer or ""),
        FIELD_MAX_LENGTHS["referrer"],
    )

    # Required fields must be present for a valid demo request.
    required_values = {"name": name, "agency": agency, "email": email}
    missing_fields = [field for field, value in required_values.items() if not value]
    # Collect invalid fields for length/format violations.
    invalid_fields = []
    if name and len(name) > FIELD_MAX_LENGTHS["name"]:
        invalid_fields.append("name")
    if agency and len(agency) > FIELD_MAX_LENGTHS["agency"]:
        invalid_fields.append("agency")
    if role and len(role) > FIELD_MAX_LENGTHS["role"]:
        invalid_fields.append("role")
    if email and (len(email) > FIELD_MAX_LENGTHS["email"] or not EMAIL_RE.fullmatch(email)):
        invalid_fields.append("email")
    if phone and (len(phone) > FIELD_MAX_LENGTHS["phone"] or not PHONE_RE.fullmatch(phone)):
        invalid_fields.append("phone")
    if notes and len(notes) > FIELD_MAX_LENGTHS["notes"]:
        invalid_fields.append("notes")

    validation_errors = sorted(set(missing_fields + invalid_fields))
    if validation_errors:
        if wants_json_response():
            return jsonify({"ok": False, "errors": validation_errors}), 400
        flash(
            "Please review the form fields: " + ", ".join(validation_errors),
            "error",
        )
        return redirect_to_demo_anchor()

    # Verify Turnstile challenge before rate-limit/storage/email work.
    turnstile_ok, turnstile_error = verify_turnstile_token(turnstile_token, client_ip)
    if not turnstile_ok:
        if wants_json_response():
            return jsonify({"ok": False, "error": turnstile_error}), 400
        flash(turnstile_error, "error")
        return redirect_to_demo_anchor()

    # Apply server-side rate limits before persisting or sending email.
    allowed, rate_message = check_and_record_rate_limit(client_ip, email)
    if not allowed:
        if wants_json_response():
            return jsonify({"ok": False, "error": rate_message}), 429
        flash(rate_message, "error")
        return redirect_to_demo_anchor()

    # Build and persist normalized lead record.
    submitted_at = utc_now()
    lead = {
        "timestamp": submitted_at.isoformat().replace("+00:00", "Z"),
        "name": name,
        "agency": agency,
        "role": role,
        "email": email,
        "phone": phone,
        "notes": notes,
        "source_ip": client_ip,
        "user_agent": clip_text(request.headers.get("User-Agent", ""), 512),
        "elapsed_ms": elapsed_ms,
        "suspicious_too_fast": not elapsed_ok,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_term": utm_term,
        "utm_content": utm_content,
        "landing_page": landing_page,
        "referrer": referrer,
    }
    append_lead(lead)

    # Attempt outbound email delivery via configured provider.
    email_sent, delivery_error = send_demo_email(lead)
    if not email_sent:
        app.logger.error("Demo email delivery failed: %s", delivery_error)
        if REQUIRE_EMAIL_DELIVERY:
            if wants_json_response():
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Request saved, but email delivery failed. Please try again or email us directly.",
                        }
                    ),
                    503,
                )
            flash(
                "We received your request, but email delivery failed. Please email us directly at "
                + CONTACT_EMAIL,
                "error",
            )
            return redirect_to_demo_anchor()

    if wants_json_response():
        return jsonify({"ok": True, "message": "Lead received"}), 200
    flash("Thanks — we received your request and will get back to you.", "success")
    return redirect_to_demo_anchor()


@app.errorhandler(404)
def page_not_found(_error):
    """Render branded 404 page."""
    return render_template("404.html", title="404 — Page not found"), 404


@app.errorhandler(500)
def internal_error(_error):
    """Render branded 500 page."""
    return render_template("500.html", title="500 — Internal server error"), 500


@app.route("/force500")
def force500():
    """Intentionally trigger HTTP 500 to test the error handler."""
    abort(500)


@app.route("/_preview/500")
def preview_500():
    """Preview the 500 template while debug mode is enabled."""
    return render_template("500.html", title="500 — Internal server error"), 500


@app.route("/robots.txt")
def robots_txt():
    """Serve robots.txt from project root."""
    return send_from_directory(BASE_DIR, "robots.txt", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """Render XML sitemap including blog routes."""
    base_url = request.url_root.rstrip("/")
    entries: List[Dict[str, str]] = [
        {"loc": f"{base_url}/", "changefreq": "weekly", "priority": "1.0"},
        {"loc": f"{base_url}/products", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base_url}/impact", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base_url}/security", "changefreq": "monthly", "priority": "0.8"},
        {"loc": f"{base_url}/grants", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base_url}/about", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base_url}/blog", "changefreq": "weekly", "priority": "0.8"},
    ]

    for post in published_blog_posts():
        post_slug = post.get("slug", "").strip()
        if not post_slug:
            continue
        post_entry = {
            "loc": f"{base_url}/blog/{post_slug}",
            "changefreq": "monthly",
            "priority": "0.7",
        }
        lastmod = (post.get("updated_at") or post.get("published_at") or "").strip()
        if lastmod:
            post_entry["lastmod"] = lastmod
        entries.append(post_entry)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for entry in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{xml_escape(entry['loc'])}</loc>")
        if entry.get("lastmod"):
            lines.append(f"    <lastmod>{xml_escape(entry['lastmod'])}</lastmod>")
        lines.append(f"    <changefreq>{xml_escape(entry['changefreq'])}</changefreq>")
        lines.append(f"    <priority>{xml_escape(entry['priority'])}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")


if __name__ == "__main__":
    app.run(debug=True)
