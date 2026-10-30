"""Chat interface entry point: `streamlit run app.py`."""

from iqm_rag.generation.chain import default_chain
from iqm_rag.ui.chat_app import run

run(default_chain)
