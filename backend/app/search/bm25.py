"""BM25 поверх разреженной матрицы частот (scipy CSC).

Своя реализация вместо готовой библиотеки нужна по трём причинам:
  * запрос приходит уже лемматизированным и с весами (расширения аббревиатур
    должны весить меньше исходных слов оператора);
  * матрица переиспользуется и для поиска по услугам, и для поиска по чанкам;
  * нужен быстрый расчёт только по колонкам запроса, без прохода по корпусу.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse

K1 = 1.4
B = 0.72


class BM25Index:
    def __init__(self, vocabulary: dict[str, int], tf: sparse.csc_matrix):
        self.vocabulary = vocabulary
        self.tf = tf.tocsc()
        self.n_docs = tf.shape[0]
        doc_len = np.asarray(tf.sum(axis=1)).ravel().astype(np.float32)
        self.doc_len = doc_len
        self.avgdl = float(doc_len.mean()) if self.n_docs else 1.0
        df = np.asarray((tf > 0).sum(axis=0)).ravel().astype(np.float32)
        self.idf = np.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5)).astype(np.float32)
        # знаменатель BM25 зависит только от документа — считаем один раз
        self._norm = (K1 * (1.0 - B + B * doc_len / max(self.avgdl, 1e-6))).astype(np.float32)

    def score(self, terms: list[str], weights: list[float] | None = None) -> np.ndarray:
        scores = np.zeros(self.n_docs, dtype=np.float32)
        if not terms:
            return scores
        if weights is None:
            weights = [1.0] * len(terms)
        seen: dict[int, float] = {}
        for term, w in zip(terms, weights):
            col = self.vocabulary.get(term)
            if col is None:
                continue
            seen[col] = max(seen.get(col, 0.0), float(w))
        for col, w in seen.items():
            start, end = self.tf.indptr[col], self.tf.indptr[col + 1]
            if start == end:
                continue
            rows = self.tf.indices[start:end]
            freq = self.tf.data[start:end].astype(np.float32)
            contrib = self.idf[col] * (freq * (K1 + 1.0)) / (freq + self._norm[rows])
            scores[rows] += w * contrib
        return scores

    def covered(self, terms: list[str]) -> list[str]:
        return [t for t in terms if t in self.vocabulary]
