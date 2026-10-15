import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from langchain_core.documents import Document

from open_webui.retrieval.utils import query_doc_with_hybrid_search
from open_webui.routers.retrieval import save_docs_to_vector_db
from open_webui.test.util.test_document_loaders import no_network


class StubEmbedder:
    """Stands in for the SentenceTransformer the router gets from get_ef."""

    def encode(self, texts, **kwargs):
        return np.array([[float(i), 1.0] for i in range(len(texts))])


def make_request(text_splitter: str, chunk_size: int, chunk_overlap: int):
    config = SimpleNamespace(
        TEXT_SPLITTER=text_splitter,
        CHUNK_SIZE=chunk_size,
        CHUNK_OVERLAP=chunk_overlap,
        TIKTOKEN_ENCODING_NAME="cl100k_base",
        RAG_EMBEDDING_ENGINE="",
        RAG_EMBEDDING_MODEL="stub",
        RAG_OPENAI_API_BASE_URL="",
        RAG_OPENAI_API_KEY="",
        RAG_OLLAMA_BASE_URL="",
        RAG_OLLAMA_API_KEY="",
        RAG_EMBEDDING_BATCH_SIZE=1,
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config, ef=StubEmbedder())))


class SaveDocsSplitterTest(unittest.TestCase):
    def _save(self, request, text: str) -> list[dict]:
        client = MagicMock()
        client.has_collection.return_value = False
        with patch("open_webui.routers.retrieval.VECTOR_DB_CLIENT", client), no_network() as calls:
            ok = save_docs_to_vector_db(
                request, [Document(page_content=text, metadata={"name": "notes"})], "c1"
            )
        self.assertEqual(calls, [])
        self.assertTrue(ok)
        return client.insert.call_args.kwargs["items"]

    def test_character_splitter(self):
        items = self._save(
            make_request("character", chunk_size=30, chunk_overlap=0),
            "First paragraph about rain.\n\nSecond paragraph about wind.",
        )
        self.assertEqual(
            [item["text"] for item in items],
            ["First paragraph about rain.", "Second paragraph about wind."],
        )
        self.assertEqual([item["metadata"]["start_index"] for item in items], [0, 29])
        self.assertEqual([item["metadata"]["name"] for item in items], ["notes", "notes"])

    def test_token_splitter(self):
        items = self._save(
            make_request("token", chunk_size=5, chunk_overlap=0),
            "one two three four five six seven eight nine ten",
        )
        self.assertEqual(
            [item["text"].strip() for item in items],
            ["one two three four five", "six seven eight nine ten"],
        )


class StubReranker:
    """Stands in for the CrossEncoder with a fixed score per passage."""

    SCORES = {
        "Heavy rain in Nairobi overnight.": 0.9,
        "Rain gauges were read in Kisumu.": 0.8,
        "Sunny skies over Mombasa.": 0.1,
    }

    def predict(self, pairs):
        return np.array([self.SCORES[passage] for _query, passage in pairs])


class HybridSearchTest(unittest.TestCase):
    def test_ensemble_and_compression_return_reranked_documents(self):
        texts = [
            "Heavy rain in Nairobi overnight.",
            "Sunny skies over Mombasa.",
            "Rain gauges were read in Kisumu.",
        ]
        metadatas = [{"source": f"doc{i}"} for i in range(len(texts))]
        collection = SimpleNamespace(documents=[texts], metadatas=[metadatas])

        client = MagicMock()
        client.search.return_value = SimpleNamespace(
            ids=[["v1", "v2"]],
            metadatas=[[{"source": "doc1"}, {"source": "doc2"}]],
            documents=[[texts[1], texts[2]]],
        )
        with patch("open_webui.retrieval.utils.VECTOR_DB_CLIENT", client), no_network() as calls:
            result = query_doc_with_hybrid_search(
                collection_name="c1",
                collection_result=collection,
                query="rain",
                embedding_function=lambda query, prefix=None: [0.0, 1.0],
                k=3,
                reranking_function=StubReranker(),
                k_reranker=3,
                r=0.5,
            )
        self.assertEqual(calls, [])
        client.search.assert_called_once()
        # Ordered by the reranker's scores; the passage scored 0.1 falls below r.
        self.assertEqual(
            result["documents"][0],
            ["Heavy rain in Nairobi overnight.", "Rain gauges were read in Kisumu."],
        )
        self.assertEqual(result["distances"][0], [0.9, 0.8])
        self.assertEqual([m["source"] for m in result["metadatas"][0]], ["doc0", "doc2"])


if __name__ == "__main__":
    unittest.main()
