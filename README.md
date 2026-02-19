# ChatPDF – Intelligent Document Question & Answer System

ChatPDF is an **AI-powered web application** that allows users to upload PDF documents and interact with them using natural language questions. The system extracts text from PDFs and leverages **LLaMA3 (via Ollama)** to generate accurate, context-aware responses.

---

## Key Features

- **Secure User Authentication** – Registration & login with bcrypt
- **PDF Upload & Text Extraction** – Quickly process documents
- **AI-Based Q&A** – Ask questions about PDF content in natural language
- **Chat History** – Save and retrieve previous interactions
- **Admin Dashboard** – Manage users and documents efficiently
- **Role-Based Access Control** – Different permissions for users and admins
- **Local AI Processing** – Data privacy with local LLaMA3 model

---

## Tech Stack

- **Backend:** Python, Flask  
- **Database:** MySQL  
- **AI Model:** LLaMA3 (via Ollama)  
- **PDF Processing:** PyPDF2  
- **Frontend:** HTML, CSS, JavaScript  

---

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/akash-joshi20/ChatPDF.git
   cd ChatPDF
