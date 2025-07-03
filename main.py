from fastapi import FastAPI
from route_api_parse import app as route_app  # If you already created the app in route_api_parse

app = FastAPI()

app.mount("/", route_app)  # Mount your actual FastAPI app
