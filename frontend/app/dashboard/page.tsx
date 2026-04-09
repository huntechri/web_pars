"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getApiBaseUrl } from "../../lib/api";
import ParserSidebar from "../../components/ParserSidebar";

type TreeNode = {
  code?: string | number;
  title: string;
  product_qty?: number;
  children?: TreeNode[];
};

type GroupedTree = Record<string, TreeNode[]>;

type JobProgress = {
  status: string;
  progress_percent: number;
  products_collected: number;
  categories_done: number;
  categories_total: number;
};

function collectDescendantCodes(node: TreeNode): string[] {
  const own = node.code ? [String(node.code)] : [];
  const childCodes = (node.children || []).flatMap(collectDescendantCodes);
  return [...own, ...childCodes];
}

function collectSelectedNodes(
  groups: GroupedTree,
  selectedCodes: Set<string>,
  parentPath: string[] = []
): Array<{ id: string; path: string[] }> {
  const result: Array<{ id: string; path: string[] }> = [];

  const walk = (node: TreeNode, path: string[]) => {
    const nextPath = [...path, node.title];
    const isSelected = !!(node.code && selectedCodes.has(String(node.code)));

    // В payload отправляем КАЖДУЮ выбранную категорию.
    // Некоторые разделы API возвращают только "прямые" товары категории,
    // поэтому исключать потомков нельзя — иначе можно получить только первую страницу (50).
    if (isSelected) {
      result.push({ id: String(node.code), path: nextPath });
    }

    (node.children || []).forEach((child) => walk(child, nextPath));
  };

  Object.values(groups).forEach((arr) => arr.forEach((n) => walk(n, parentPath)));
  return result;
}

function TreeItem({
  node,
  selected,
  toggle,
  level = 0
}: {
  node: TreeNode;
  selected: Set<string>;
  toggle: (node: TreeNode, checked: boolean) => void;
  level?: number;
}) {
  const code = node.code ? String(node.code) : undefined;
  const checked = code ? selected.has(code) : false;
  const levelClass = `tree-level-${Math.min(level, 6)}`;

  return (
    <div className={`tree-node ${levelClass}`}>
      <label className="row">
        {code ? (
          <input
            className="tree-indent"
            type="checkbox"
            checked={checked}
            onChange={(e) => toggle(node, e.target.checked)}
          />
        ) : (
          <span className="tree-indent" />
        )}
        <span>{node.title}</span>
        <span className="category-qty">({node.product_qty ?? 0} шт.)</span>
      </label>
      {(node.children || []).map((child) => (
        <TreeItem key={`${child.code || child.title}-${level}`} node={child} selected={selected} toggle={toggle} level={level + 1} />
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [categories, setCategories] = useState<GroupedTree>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [maxProducts, setMaxProducts] = useState<string>("");
  const [jobId, setJobId] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [jobError, setJobError] = useState("");
  const [jobProgress, setJobProgress] = useState<JobProgress | null>(null);
  const [jobStartedAtMs, setJobStartedAtMs] = useState<number | null>(null);
  const [jobProductsTotalEstimate, setJobProductsTotalEstimate] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [refreshingCategories, setRefreshingCategories] = useState(false);

  useEffect(() => {
    const t = localStorage.getItem("token");
    if (!t) {
      router.replace("/login");
      return;
    }
    setToken(t);

    apiFetch("/api/auth/me", {}, t)
      .then(() => apiFetch("/api/categories/tree", {}, t))
      .then((tree) => setCategories(tree))
      .catch(() => {
        localStorage.removeItem("token");
        router.replace("/login");
      });
  }, [router]);

  useEffect(() => {
    if (!jobId || !token) {
      return;
    }

    const timer = setInterval(async () => {
      try {
        const [job, progress] = await Promise.all([
          apiFetch(`/api/parser/jobs/${jobId}`, {}, token),
          apiFetch(`/api/parser/jobs/${jobId}/progress`, {}, token)
        ]);
        setJobStatus(job.status);
        setJobError(job.error || "");
        setJobProgress(progress);
        if (!jobStartedAtMs && (job.status === "running" || progress.status === "running")) {
          setJobStartedAtMs(Date.now());
        }
      } catch {
        // ignore poll errors
      }
    }, 3000);

    return () => clearInterval(timer);
  }, [jobId, token, jobStartedAtMs]);

  const selectedCount = selected.size;

  const payloadCategories = useMemo(
    () => collectSelectedNodes(categories, selected),
    [categories, selected]
  );

  const categoryQtyByCode = useMemo(() => {
    const m = new Map<string, number>();
    const walk = (node: TreeNode) => {
      if (node.code) {
        m.set(String(node.code), Number(node.product_qty || 0));
      }
      (node.children || []).forEach(walk);
    };

    Object.values(categories).forEach((nodes) => nodes.forEach(walk));
    return m;
  }, [categories]);

  const selectedProductsEstimate = useMemo(() => {
    let total = 0;
    selected.forEach((code) => {
      total += categoryQtyByCode.get(code) || 0;
    });
    return total;
  }, [selected, categoryQtyByCode]);

  const productsSpeedPerMinute = useMemo(() => {
    if (!jobProgress || !jobStartedAtMs) {
      return 0;
    }

    const elapsedMs = Date.now() - jobStartedAtMs;
    if (elapsedMs <= 0) {
      return 0;
    }

    const elapsedMinutes = elapsedMs / 60000;
    if (elapsedMinutes <= 0) {
      return 0;
    }

    return jobProgress.products_collected / elapsedMinutes;
  }, [jobProgress, jobStartedAtMs, jobStatus]);

  function toggleNode(node: TreeNode, checked: boolean) {
    const codes = collectDescendantCodes(node);
    setSelected((prev) => {
      const next = new Set(prev);
      codes.forEach((c) => {
        if (checked) next.add(c);
        else next.delete(c);
      });
      return next;
    });
  }

  async function runParser() {
    if (!token || payloadCategories.length === 0) {
      return;
    }

    setLoading(true);
    setJobError("");
    try {
      const job = await apiFetch(
        "/api/parser/run",
        {
          method: "POST",
          body: JSON.stringify({
            selected_categories: payloadCategories,
            max_products_per_cat: maxProducts ? Number(maxProducts) : null
          })
        },
        token
      );
      setJobId(job.id);
      setJobStatus(job.status);
      setJobStartedAtMs(Date.now());
      setJobProductsTotalEstimate(selectedProductsEstimate);
      setJobProgress({
        status: job.status,
        progress_percent: 0,
        products_collected: 0,
        categories_done: 0,
        categories_total: payloadCategories.length
      });
    } catch (e) {
      setJobError("Не удалось запустить парсер");
    } finally {
      setLoading(false);
    }
  }

  const productsProgressMax = Math.max(
    1,
    jobProductsTotalEstimate,
    jobProgress?.products_collected || 0
  );

  function downloadCsv() {
    if (!jobId || !token) {
      return;
    }
    const url = `${getApiBaseUrl()}/api/parser/jobs/${jobId}/download`;
    fetch(url, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error("download error");
        }
        return res.blob();
      })
      .then((blob) => {
        const link = document.createElement("a");
        const objectUrl = URL.createObjectURL(blob);
        link.href = objectUrl;
        link.download = `petrovich_${jobId}.csv`;
        document.body.appendChild(link);
        link.click();
        URL.revokeObjectURL(objectUrl);
        link.remove();
      })
      .catch(() => setJobError("Не удалось скачать CSV"));
  }

  async function refreshCategories() {
    if (!token) {
      return;
    }

    setRefreshingCategories(true);
    setJobError("");
    try {
      await apiFetch(
        "/api/categories/refresh",
        {
          method: "POST"
        },
        token
      );
      const freshTree = await apiFetch("/api/categories/tree", {}, token);
      setCategories(freshTree);
      setSelected(new Set());
    } catch {
      setJobError("Не удалось обновить категории из источника");
    } finally {
      setRefreshingCategories(false);
    }
  }

  return (
    <main className="app-shell">
      <ParserSidebar />

      <section className="app-content app-content-wide dashboard-content">
      <div className="card dashboard-main-card">
        <div className="row space-between">
          <h1 className="m-0">Парсер Петрович (web)</h1>
          <span />
        </div>

        <p>Выбрано категорий: {selectedCount}</p>

        <div className="mb-12">
          <label htmlFor="max-products">Лимит товаров на категорию (опционально)</label>
          <input
            id="max-products"
            placeholder="например, 100"
            value={maxProducts}
            onChange={(e) => setMaxProducts(e.target.value)}
          />
        </div>

        <button onClick={runParser} disabled={loading || payloadCategories.length === 0}>
          {loading ? "Запуск..." : "Запустить"}
        </button>

        <div className="mt-20 dashboard-status">
          <h3>Статус</h3>
          <p>Job ID: {jobId || "—"}</p>
          <p>Состояние: {jobStatus || "—"}</p>
          {jobId ? (
            <div className="progress-wrap">
              <div className="progress-label-row">
                <span>
                  Товары: {jobProgress?.products_collected ?? 0}
                  {jobProductsTotalEstimate > 0 ? ` / ${jobProductsTotalEstimate}` : ""} шт.
                </span>
              </div>
              <progress
                className="progress-native"
                max={productsProgressMax}
                value={Math.max(0, Math.min(productsProgressMax, jobProgress?.products_collected ?? 0))}
              />
              <p className="progress-sub">
                Категории: {jobProgress?.categories_done ?? 0}/{jobProgress?.categories_total ?? 0}
              </p>
              <p className="progress-sub">
                Скорость: {Number.isFinite(productsSpeedPerMinute) ? productsSpeedPerMinute.toFixed(1) : "0.0"} шт./мин
              </p>
            </div>
          ) : null}
          {jobError ? <p className="error">{jobError}</p> : null}
          <div className="row dashboard-actions">
            <button onClick={downloadCsv} disabled={jobStatus !== "done"}>
              Скачать CSV
            </button>
            <button
              onClick={() => router.push(`/results?jobId=${encodeURIComponent(jobId)}`)}
              disabled={jobStatus !== "done" || !jobId}
            >
              Открыть таблицу
            </button>
          </div>
        </div>
      </div>

      <div className="card mt-16 dashboard-categories-card">
        <div className="row space-between">
          <h2 className="m-0">Категории</h2>
          <button onClick={refreshCategories} disabled={refreshingCategories || loading}>
            {refreshingCategories ? "Обновляем..." : "Обновить категории"}
          </button>
        </div>

        <div className="dashboard-categories-scroll">
          {Object.entries(categories).map(([group, nodes]) => (
            <section key={group} className="section-gap">
              <h3>{group}</h3>
              {nodes.map((node) => (
                <TreeItem key={`${node.code || node.title}-${group}`} node={node} selected={selected} toggle={toggleNode} />
              ))}
            </section>
          ))}
        </div>
      </div>
      </section>
    </main>
  );
}
