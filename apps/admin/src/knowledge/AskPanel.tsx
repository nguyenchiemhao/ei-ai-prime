import { type FormEvent, Fragment, useEffect, useId, useRef, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { type AskEvent, type AskPassage, askCollection } from "../api/ask";
import type { ApiResult } from "../api/client";
import type { CollectionDetail } from "../api/collections";
import { parseGroups } from "./groups";

interface Props {
  workspaceId: string;
  collection: CollectionDetail;
  onSessionExpired(): void;
  onNotFound(): void;
}

type Language = "vi" | "en";
type Principal = "authenticated" | "anonymous";
type Answer = { outcome: "answering" | "answered" | "not_found"; text: string };

const PRINCIPALS: readonly Principal[] = ["authenticated", "anonymous"];
const QUESTION_MAX = 2000;
const UNAUTHENTICATED = 401;
const FORBIDDEN = 403;
const NOT_FOUND = 404;
const UNPROCESSABLE = 422;
const ABORTED = "aborted";
const CITATION = /\[(\d+)\]/;
const MODEL_UNAVAILABLE_KEY = "admin.knowledge.ask.modelUnavailable";
// The ask accepts up to 100 groups (R32), not the collection form's 20: its own message.
const INVALID_GROUP_KEY = "admin.knowledge.ask.invalidGroup";

// Splits answer text into plain text and inline citation spans (no HTML is ever injected).
// Input: text (string). Output: the rendered nodes
function withCitations(text: string) {
  return text.split(CITATION).map((part, index) =>
    index % 2 === 1 ? (
      <span key={index} className="ask-citation" data-testid="ask-citation">
        {`[${part}]`}
      </span>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

// The i18n key of the message for a failed ask (contract "UI" error mapping).
// Input: status and code of the failure. Output: the i18n key
function failureKey(status: number, code: string): string {
  if (status === FORBIDDEN) return "admin.knowledge.error.forbidden";
  if (status === UNPROCESSABLE && code === "invalid_group") return INVALID_GROUP_KEY;
  if (status === UNPROCESSABLE) return "admin.knowledge.error.generic";
  return MODEL_UNAVAILABLE_KEY;
}

/** "Ask this collection": try a question against the collection as a chosen principal (EA-37). */
export function AskPanel({ workspaceId, collection, onSessionExpired, onNotFound }: Props) {
  const { t } = useTranslation();
  const ids = {
    principal: useId(),
    groups: useId(),
    groupsHelp: useId(),
    groupsError: useId(),
    question: useId(),
  };
  const [principal, setPrincipal] = useState<Principal>("authenticated");
  const [groupsText, setGroupsText] = useState(
    collection.access_level === "restricted" ? collection.groups.join(", ") : "",
  );
  const [question, setQuestion] = useState("");
  const [answering, setAnswering] = useState(false);
  const [language, setLanguage] = useState<Language | null>(null);
  const [passages, setPassages] = useState<AskPassage[] | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [cited, setCited] = useState<number[]>([]);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [groupsError, setGroupsError] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  // Leaving the page cancels the running request.
  useEffect(() => () => controllerRef.current?.abort(), []);

  // The streamed text is shown as it arrives; `done` replaces it, `error` removes it (R18, R33).
  function onEvent(event: AskEvent) {
    if (event.type === "passages") {
      setLanguage(event.language);
      setPassages(event.passages);
    } else if (event.type === "delta") {
      setAnswer((current) => ({ outcome: "answering", text: (current?.text ?? "") + event.text }));
    } else if (event.type === "done") {
      setAnswer({ outcome: event.outcome, text: event.outcome === "answered" ? event.answer : "" });
      setCited(event.citations);
    } else {
      setAnswer(null);
      setErrorKey(MODEL_UNAVAILABLE_KEY);
    }
  }

  // Shows a failed request: sign-in flow, Not found page, or one message.
  function fail(result: Extract<ApiResult<void>, { ok: false }>) {
    if (result.code === ABORTED) return;
    setAnswer(null);
    if (result.status === UNAUTHENTICATED) onSessionExpired();
    else if (result.status === NOT_FOUND) onNotFound();
    else if (result.status === UNPROCESSABLE && result.code === "invalid_group") {
      setGroupsError(true);
    } else setErrorKey(failureKey(result.status, result.code));
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (answering || text === "") return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setAnswering(true);
    setLanguage(null);
    setPassages(null);
    setAnswer({ outcome: "answering", text: "" });
    setCited([]);
    setErrorKey(null);
    setGroupsError(false);
    const groups = principal === "authenticated" ? parseGroups(groupsText) : [];
    let finished = false;
    const result = await askCollection(
      workspaceId,
      collection.id,
      { question: text, principal: { kind: principal, groups } },
      (item) => {
        if (controller.signal.aborted) return;
        if (item.type === "done" || item.type === "error") finished = true;
        onEvent(item);
      },
      controller.signal,
    );
    if (controller.signal.aborted) return;
    if (!result.ok) fail(result);
    else if (!finished) {
      setAnswer(null);
      setErrorKey(MODEL_UNAVAILABLE_KEY);
    }
    setAnswering(false);
  }

  const noPassages = passages !== null && passages.length === 0;

  return (
    <section className="members-card" data-testid="ask-panel">
      <div>
        <h2 className="members-card-title">{t("admin.knowledge.ask.title")}</h2>
        <p className="ask-helper">{t("admin.knowledge.ask.helper")}</p>
      </div>
      <form className="ask-form" onSubmit={(event) => void ask(event)}>
        <div className="ask-principal-row">
          <label className="field" htmlFor={ids.principal}>
            <span className="field-label">{t("admin.knowledge.ask.principalLabel")}</span>
            <select
              id={ids.principal}
              className="field-input"
              data-testid="ask-principal"
              value={principal}
              onChange={(event) => setPrincipal(event.target.value as Principal)}
            >
              {PRINCIPALS.map((kind) => (
                <option key={kind} value={kind}>
                  {t(`admin.knowledge.ask.principal.${kind}`)}
                </option>
              ))}
            </select>
          </label>
          {principal === "authenticated" ? (
            <div className="field ask-groups">
              <label className="field" htmlFor={ids.groups}>
                <span className="field-label">{t("admin.knowledge.ask.groupsLabel")}</span>
              </label>
              <input
                id={ids.groups}
                className="field-input"
                data-testid="ask-groups"
                type="text"
                autoComplete="off"
                value={groupsText}
                aria-invalid={groupsError}
                aria-describedby={
                  groupsError ? `${ids.groupsHelp} ${ids.groupsError}` : ids.groupsHelp
                }
                onChange={(event) => setGroupsText(event.target.value)}
              />
              <span className="field-help" id={ids.groupsHelp}>
                {t("admin.knowledge.ask.groupsHelp")}
              </span>
              {groupsError ? (
                <span
                  className="field-error"
                  id={ids.groupsError}
                  role="alert"
                  data-testid="ask-groups-error"
                >
                  {t(INVALID_GROUP_KEY)}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="ask-question-row">
          <label className="ask-question" htmlFor={ids.question}>
            <span className="ask-visually-hidden">{t("admin.knowledge.ask.questionLabel")}</span>
            <input
              id={ids.question}
              className="field-input"
              data-testid="ask-question"
              type="text"
              autoComplete="off"
              maxLength={QUESTION_MAX}
              placeholder={t("admin.knowledge.ask.questionPlaceholder")}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="button-primary"
            data-testid="ask-submit"
            disabled={answering || question.trim() === ""}
          >
            {t("admin.knowledge.ask.submit")}
          </button>
        </div>
      </form>
      {errorKey ? (
        <p className="knowledge-alert" role="alert" data-testid="ask-error">
          {t(errorKey)}
        </p>
      ) : null}
      {answer ? (
        <div
          className="ask-answer"
          data-testid="ask-answer"
          data-outcome={answer.outcome}
          data-language={language ?? undefined}
          aria-busy={answer.outcome === "answering" ? true : undefined}
        >
          {answer.outcome === "not_found" ? (
            noPassages ? (
              <span data-testid="ask-no-passages">{t("admin.knowledge.ask.noPassages")}</span>
            ) : (
              t("admin.knowledge.ask.notFound", { lng: language ?? undefined })
            )
          ) : (
            withCitations(answer.text)
          )}
        </div>
      ) : null}
      {passages && passages.length > 0 ? (
        <section className="ask-passages" data-testid="ask-passages">
          <h3 className="ask-passages-title">{t("admin.knowledge.ask.passagesTitle")}</h3>
          <ul className="ask-passage-list">
            {passages.map((passage) => {
              const isCited = cited.includes(passage.number);
              return (
                <li
                  key={passage.number}
                  className="ask-passage"
                  data-testid="ask-passage"
                  data-number={passage.number}
                  data-cited={isCited ? "true" : "false"}
                >
                  <span className="ask-passage-number">{isCited ? `[${passage.number}]` : ""}</span>
                  <span className="ask-passage-source" data-testid="ask-passage-source">
                    {sourceText(passage, t)}
                  </span>
                  <span className="ask-passage-score" data-testid="ask-passage-score">
                    {passage.score.toFixed(2)}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

// "Title", then " · Section" when known, then " · p. N" when the page is known (R33).
// Input: the passage and t. Output: the source line
function sourceText(passage: AskPassage, t: TFunction): string {
  const parts = [passage.title];
  if (passage.section !== null) parts.push(passage.section);
  if (passage.page !== null) parts.push(t("admin.knowledge.ask.page", { page: passage.page }));
  return parts.join(" · ");
}
