from setuptools import setup, find_packages

setup(
    name="rag-plugin",
    version="0.1.0",
    description="FANUC RAG Knowledge Base — pluggable retrieval + generation",
    py_modules=["retriever", "rag_core"],
    install_requires=["chromadb", "numpy", "torch", "transformers", "pyyaml"],
    entry_points={
        "console_scripts": [
            "rag-flywheel=rag_flywheel_batch:main",
            "rag-smoke=rag_flywheel_batch:smoke",
        ],
    },
)
