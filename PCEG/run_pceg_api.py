#!/usr/bin/env python3
"""Standalone launcher for PCEG REST API on port 8002."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import uvicorn
from fastapi import FastAPI
from pceg_api import router

app = FastAPI(title="VeriVerse PCEG API")
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
