"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch } from "../../lib/api";
import ParserSidebar from "../../components/ParserSidebar";

type JobItem = {
  id: string;
  status: string;
  output_file?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

type ResultRow = {
  id: number;
  article?: string | null;
  name: string;
  unit?: string | null;
  price?: string | null;
  brand?: string | null;
  weight?: string | null;
  level1?: string | null;
  level2?: string | null;
  level3?: string | null;
  level4?: string | null;
  image?: string | null;
  url?: string | null;
  supplier?: string | null;
};

type JobResultsResponse = {
  job_id: string;
  total: number;
  limit: number;
  offset: number;
  items: ResultRow[];
};

const PAGE_SIZE = 50;

export default function ResultsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryJobId = searchParams.get("jobId") || "";

  const [token, setToken] = useState("");
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<ResultRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = localStorage.getItem("token");
    if (!t) {
      router.replace("/login");
      return;
    }
    setToken(t);
  }, [router]);

  useEffect(() => {
    if (!token) {
      return;
    }

    setLoadingJobs(true);
    setError("");
    apiFetch("/api/parser/jobs", {}, token)
      .then((allJobs: JobItem[]) => {
        const doneJobs = allJobs.filter((j) => j.status === "done");
        setJobs(doneJobs);

        if (queryJobId && doneJobs.some((j) => j.id === queryJobId)) {
          setSelectedJobId(queryJobId);
          return;
        }

        setSelectedJobId(doneJobs[0]?.id || "");
      })
      .catch(() => setError("Не удалось загрузить список задач"))
      .finally(() => setLoadingJobs(false));
  }, [token, queryJobId]);

  useEffect(() => {
    if (!token || !selectedJobId) {
      setRows([]);
      setTotal(0);
      return;
    }

    setLoadingRows(true);
    setError("");
    apiFetch(`/api/parser/jobs/${selectedJobId}/results?limit=${PAGE_SIZE}&offset=${offset}`, {}, token)
      .then((result: JobResultsResponse) => {
        setRows(result.items || []);
        setTotal(result.total || 0);
      })
      .catch(() => setError("Не удалось загрузить результаты"))
      .finally(() => setLoadingRows(false));
  }, [token, selectedJobId, offset]);

  const page = useMemo(() => Math.floor(offset / PAGE_SIZE) + 1, [offset]);
  const pagesTotal = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);

  return (
    <main className="app-shell">
      <ParserSidebar />

      <section className="app-content app-content-wide">
      <div className="card results-card">
        <div className="row space-between">
          <h1 className="m-0">Результаты парсинга</h1>
          <button onClick={() => router.push("/dashboard")}>Назад</button>
        </div>

        <div className="mt-16 row">
          <label htmlFor="job-select">Задача:</label>
          <select
            id="job-select"
            className="select-input"
            value={selectedJobId}
            onChange={(e) => {
              setSelectedJobId(e.target.value);
              setOffset(0);
            }}
            disabled={loadingJobs || jobs.length === 0}
          >
            {jobs.length === 0 ? <option value="">Нет завершенных задач</option> : null}
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.id} · {new Date(job.created_at).toLocaleString("ru-RU")}
              </option>
            ))}
          </select>
        </div>

        {error ? <p className="error">{error}</p> : null}

        <div className="mt-16 table-wrap results-table-wrap">
          <table className="results-table">
            <thead>
              <tr>
                <th>Артикул</th>
                <th>Наименование</th>
                <th>Цена</th>
                <th>Ед.</th>
                <th>Бренд</th>
                <th>Вес</th>
                <th>LV1</th>
                <th>LV2</th>
                <th>LV3</th>
                <th>LV4</th>
                <th>Источник</th>
                <th>Ссылка</th>
              </tr>
            </thead>
            <tbody>
              {loadingRows ? (
                <tr>
                  <td colSpan={12}>Загрузка...</td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={12}>Нет данных</td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.article || ""}</td>
                    <td>{row.name || ""}</td>
                    <td>{row.price || ""}</td>
                    <td>{row.unit || ""}</td>
                    <td>{row.brand || ""}</td>
                    <td>{row.weight || ""}</td>
                    <td>{row.level1 || ""}</td>
                    <td>{row.level2 || ""}</td>
                    <td>{row.level3 || ""}</td>
                    <td>{row.level4 || ""}</td>
                    <td>{row.supplier || ""}</td>
                    <td>
                      {row.url ? (
                        <a href={row.url} target="_blank" rel="noreferrer">
                          Открыть
                        </a>
                      ) : (
                        ""
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="row mt-16 space-between">
          <span>
            Страница {page} / {pagesTotal} · Всего строк: {total}
          </span>
          <div className="row">
            <button
              onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
              disabled={offset === 0 || loadingRows}
            >
              Назад
            </button>
            <button
              onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total || loadingRows}
            >
              Вперед
            </button>
          </div>
        </div>
      </div>
      </section>
    </main>
  );
}
