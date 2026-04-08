"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getApiBaseUrl } from "../../lib/api";

type TreeNode = {
  code?: string | number;
  title: string;
  children?: TreeNode[];
};

type GroupedTree = Record<string, TreeNode[]>;

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
    if (node.code && selectedCodes.has(String(node.code))) {
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
        const job = await apiFetch(`/api/parser/jobs/${jobId}`, {}, token);
        setJobStatus(job.status);
        setJobError(job.error || "");
      } catch {
        // ignore poll errors
      }
    }, 3000);

    return () => clearInterval(timer);
  }, [jobId, token]);

  const selectedCount = selected.size;

  const payloadCategories = useMemo(
    () => collectSelectedNodes(categories, selected),
    [categories, selected]
  );

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
    } catch (e) {
      setJobError("Не удалось запустить парсер");
    } finally {
      setLoading(false);
    }
  }

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
    <main className="container">
      <div className="card">
        <div className="row space-between">
          <h1 className="m-0">Парсер Петрович (web)</h1>
          <button
            onClick={() => {
              localStorage.removeItem("token");
              router.push("/login");
            }}
          >
            Выйти
          </button>
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

        <div className="mt-20">
          <h3>Статус</h3>
          <p>Job ID: {jobId || "—"}</p>
          <p>Состояние: {jobStatus || "—"}</p>
          {jobError ? <p className="error">{jobError}</p> : null}
          <button onClick={downloadCsv} disabled={jobStatus !== "done"}>
            Скачать CSV
          </button>
        </div>
      </div>

      <div className="card mt-16">
        <div className="row space-between">
          <h2 className="m-0">Категории</h2>
          <button onClick={refreshCategories} disabled={refreshingCategories || loading}>
            {refreshingCategories ? "Обновляем..." : "Обновить категории"}
          </button>
        </div>
        {Object.entries(categories).map(([group, nodes]) => (
          <section key={group} className="section-gap">
            <h3>{group}</h3>
            {nodes.map((node) => (
              <TreeItem key={`${node.code || node.title}-${group}`} node={node} selected={selected} toggle={toggleNode} />
            ))}
          </section>
        ))}
      </div>
    </main>
  );
}
