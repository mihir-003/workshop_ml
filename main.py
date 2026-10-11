import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.exception import CustomException
from src.logger import get_logger
from src.pipeline.predict_pipeline import CustomData, PredictPipeline

from nlp_pretrained.ner_tagger import get_pos_tags, extract_entities
from nlp_pretrained.embedding import most_similar_words
from nlp_pretrained.sentiment_analyzer import analyze_sentiment

from clinic.database import init_db
from clinic.routes import router as clinic_router
from smart_care.router import router as smart_care_router
from clinic.admin_routes import router as admin_router


# ---------------------------------------------------------
# LOGGER
# ---------------------------------------------------------

logger = get_logger(__name__)


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs when the FastAPI application starts.
    Initializes the Sanjeevani MySQL database tables.
    """

    logger.info("Starting application...")

    try:
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    yield

    logger.info("Application shutting down...")

from clinic.slot_service import with_slot_cleanup
lifespan = with_slot_cleanup(lifespan)


# ---------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------

from care_assistant.router import router as assistant_router
from clinic.admin_treatment_routes import router as admin_treatment_router
app = FastAPI(
    title="Sanjeevani - Covid Prediction Clinic",
    description="AI powered healthcare and Covid prediction application",
    version="1.0.0",
    lifespan=lifespan
)


# ---------------------------------------------------------
# STATIC FILES
# ---------------------------------------------------------

# Your auth.css should be located here:
#
# static/
# └── auth.css
#
app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


# ---------------------------------------------------------
# TEMPLATE DIRECTORY
# ---------------------------------------------------------

templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------
# CLINIC ROUTES
# ---------------------------------------------------------

# Login
# Signup
# Logout
# Doctor availability
# Appointments
# Chatbot
#
# These routes are handled inside clinic/routes.py

app.include_router(clinic_router)
app.include_router(smart_care_router)
app.include_router(assistant_router)
app.include_router(admin_router)
app.include_router(admin_treatment_router)


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    logger.info("Home page accessed...")

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


# ---------------------------------------------------------
# COVID PREDICTION - GET
# ---------------------------------------------------------

@app.get("/predict", response_class=HTMLResponse)
async def predict_form(request: Request):

    logger.info("Prediction form page accessed...")

    return templates.TemplateResponse(
        request=request,
        name="predict.html",
        context={
            "result": None
        }
    )


# ---------------------------------------------------------
# COVID PREDICTION - POST
# ---------------------------------------------------------

@app.post("/predict", response_class=HTMLResponse)
async def predict_result(
    request: Request,
    age: int = Form(...),
    gender: str = Form(...),
    fever: float = Form(...),
    cough: str = Form(...),
    city: str = Form(...)
):

    try:

        logger.info(
            f"Prediction request received :: "
            f"age={age}, "
            f"gender={gender}, "
            f"fever={fever}, "
            f"cough={cough}, "
            f"city={city}"
        )

        # -------------------------------------------------
        # Convert incoming form data into dataframe
        # -------------------------------------------------

        custom_data = CustomData(
            age=age,
            gender=gender,
            fever=fever,
            cough=cough,
            city=city
        )

        data_df = custom_data.get_data_as_dataframe()


        # -------------------------------------------------
        # Prediction pipeline
        # -------------------------------------------------

        predict_pipeline = PredictPipeline()

        result, probability = predict_pipeline.predict(data_df)


        # -------------------------------------------------
        # Return prediction
        # -------------------------------------------------

        return templates.TemplateResponse(
            request=request,
            name="predict.html",
            context={
                "result": result,
                "probability": probability,

                "form_data": {
                    "age": age,
                    "gender": gender,
                    "fever": fever,
                    "cough": cough,
                    "city": city
                }
            }
        )


    except Exception as e:

        logger.error(f"Prediction failed: {e}")

        raise CustomException(e, sys)


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
async def health_check():

    logger.info("Monitoring health endpoint...")

    return {
        "status": "ok",
        "application": "Sanjeevani"
    }


# =========================================================
# NLP PRETRAINED SECTION
# =========================================================


# ---------------------------------------------------------
# NLP PAGE - GET
# ---------------------------------------------------------

@app.get(
    "/pretrained-nlp",
    response_class=HTMLResponse
)
async def pretrained_nlp_form(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="pretrained_nlp.html",
        context={
            "result": None,

            "form_data": {
                "query": ""
            },

            "error": None
        }
    )


# ---------------------------------------------------------
# NLP PAGE - POST
# ---------------------------------------------------------

@app.post(
    "/pretrained-nlp",
    response_class=HTMLResponse
)
async def pretrained_nlp_analysis(
    request: Request,
    query: str = Form(...)
):

    try:

        # -------------------------------------------------
        # CLEAN INPUT
        # -------------------------------------------------

        query = query.strip()


        if not query:

            return templates.TemplateResponse(
                request=request,
                name="pretrained_nlp.html",
                context={
                    "result": None,

                    "form_data": {
                        "query": ""
                    },

                    "error": "Please enter some text..."
                }
            )


        # -------------------------------------------------
        # POS TAGGING
        # -------------------------------------------------

        pos_tags = get_pos_tags(query)


        # -------------------------------------------------
        # NAMED ENTITY RECOGNITION
        # -------------------------------------------------

        entities = extract_entities(query)


        # -------------------------------------------------
        # SENTIMENT ANALYSIS
        # -------------------------------------------------

        sentiment = analyze_sentiment(query)


        # -------------------------------------------------
        # WORD EMBEDDINGS
        # -------------------------------------------------

        similar_words = []

        words = query.split()


        if words:

            first_word = words[0].lower()

            try:

                similar_words = most_similar_words(
                    first_word,
                    topn=5
                )

            except Exception as e:

                logger.warning(
                    f"GloVe similarity failed for "
                    f"{first_word}: {e}"
                )

                similar_words = []


        # -------------------------------------------------
        # FINAL RESULT
        # -------------------------------------------------

        result = {

            "query": query,

            "pos_tags": pos_tags,

            "entities": entities,

            "similar_words": similar_words,

            "sentiment": sentiment
        }


        # -------------------------------------------------
        # RENDER RESULT
        # -------------------------------------------------

        return templates.TemplateResponse(
            request=request,
            name="pretrained_nlp.html",
            context={

                "result": result,

                "form_data": {
                    "query": query
                },

                "error": None
            }
        )


    except Exception as e:

        logger.error(
            f"Error occurred in pretrained NLP analysis: {e}"
        )

        return templates.TemplateResponse(
            request=request,
            name="pretrained_nlp.html",
            context={

                "result": None,

                "form_data": {
                    "query": query
                },

                "error": str(e)
            }
        )


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )