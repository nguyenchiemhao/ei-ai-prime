import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  type AccessChange,
  type CollectionItem,
  type CollectionUpdate,
  changeCollectionAccess,
  createCollection,
  updateCollection,
} from "../api/collections";
import type { ApiResult } from "../api/client";
import { useDialogKeys } from "../components/useDialogKeys";
import { ConfirmPublicDialog } from "./ConfirmPublicDialog";
import { knowledgeErrorKey } from "./errors";
import { parseGroups } from "./groups";
import { type AccessLevel, isAccessLevel } from "./labels";

interface Props {
  mode: "create" | "edit";
  workspaceId: string;
  collection?: CollectionItem;
  /** Holds collections.access.manage; the API checks it again. */
  canManageAccess: boolean;
  onClose(): void;
  onSaved(item: CollectionItem): void;
  /** The session ended: the shell sends the user to sign in. */
  onSessionExpired(): void;
  /** The collection no longer exists (edit mode). */
  onNotFound?(): void;
}

type SaveResult = ApiResult<CollectionItem>;

const NAME_MAX = 200;
const UNAUTHENTICATED = 401;
const NOT_FOUND = 404;
const GROUPS_REQUIRED_KEY = "admin.knowledge.error.groupsRequired";
const LEVELS: readonly AccessLevel[] = ["public", "authenticated", "restricted"];

// Lower-cases, NFC-normalises and de-duplicates groups the way the API stores them.
// Input: groups (string[]). Output: string[]
const normaliseGroups = (groups: readonly string[]): string[] => [
  ...new Set(groups.map((group) => group.normalize("NFC").toLowerCase())),
];

// Turns a subtitle input into the API value: trimmed, empty becomes null.
// Input: text (string). Output: string | null
const subtitleValue = (text: string): string | null => (text.trim() === "" ? null : text.trim());

/** Modal to create a collection or edit its access and settings. Escape and Cancel close it. */
export function CollectionDialog({
  mode,
  workspaceId,
  collection,
  canManageAccess,
  onClose,
  onSaved,
  onSessionExpired,
  onNotFound,
}: Props) {
  const { t } = useTranslation();
  const titleId = useId();
  const helpId = useId();
  const groupsHelpId = useId();
  const groupsErrorId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const groupsRef = useRef<HTMLInputElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const wasConfirmingRef = useRef(false);
  const savedRef = useRef<CollectionItem | undefined>(collection);
  const isEdit = mode === "edit";
  const accessLocked = isEdit && !canManageAccess;
  const localOnlyLocked = accessLocked && collection?.local_only === true;
  const initialLevel =
    collection && isAccessLevel(collection.access_level)
      ? collection.access_level
      : "authenticated";
  const [name, setName] = useState(collection?.name ?? "");
  const [subtitle, setSubtitle] = useState(collection?.subtitle ?? "");
  const [level, setLevel] = useState<AccessLevel>(initialLevel);
  const [groupsText, setGroupsText] = useState((collection?.groups ?? []).join(", "));
  const [localOnly, setLocalOnly] = useState(collection?.local_only ?? false);
  const [groupsError, setGroupsError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const close = () => {
    if (savedRef.current && savedRef.current !== collection) onSaved(savedRef.current);
    else onClose();
  };
  const onKeyDown = useDialogKeys(dialogRef, close);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // When the Public confirmation closes, focus goes back to the submit button of the form.
  useEffect(() => {
    if (wasConfirmingRef.current && !confirming) submitRef.current?.focus();
    wasConfirmingRef.current = confirming;
  }, [confirming]);

  // Creates the collection. Groups travel only with the restricted level.
  function create(groups: string[]): Promise<SaveResult> {
    return createCollection(workspaceId, {
      name: name.trim(),
      subtitle: subtitleValue(subtitle),
      access_level: level,
      groups: level === "restricted" ? groups : [],
      local_only: localOnly,
    });
  }

  // Edits the collection: settings first, then the access, each only when it changed.
  // Input: groups (string[]). Output: the last result, or null when nothing changed.
  async function edit(groups: string[]): Promise<SaveResult | null> {
    const current = savedRef.current;
    if (!current) return null;
    const update: CollectionUpdate = {};
    if (name.trim() !== current.name) update.name = name.trim();
    if (subtitleValue(subtitle) !== current.subtitle) update.subtitle = subtitleValue(subtitle);
    if (localOnly !== current.local_only) update.local_only = localOnly;
    const nextGroups = level === "restricted" ? groups : [];
    const accessChanged =
      canManageAccess &&
      (level !== current.access_level ||
        normaliseGroups(nextGroups).join("\n") !== normaliseGroups(current.groups).join("\n"));
    let result: SaveResult | null = null;
    if (Object.keys(update).length > 0) {
      result = await updateCollection(workspaceId, current.id, update);
      if (!result.ok) return result;
      savedRef.current = result.data;
    }
    if (accessChanged) {
      const change: AccessChange = { access_level: level, groups: nextGroups };
      result = await changeCollectionAccess(workspaceId, current.id, change);
    }
    return result;
  }

  // Sends the request(s) of the form and reports the outcome.
  async function save() {
    const groups = parseGroups(groupsText);
    setSending(true);
    setError(null);
    const result = isEdit ? await edit(groups) : await create(groups);
    setSending(false);
    if (result === null) onClose();
    else if (result.ok) onSaved(result.data);
    else if (result.status === UNAUTHENTICATED) onSessionExpired();
    else if (isEdit && result.status === NOT_FOUND && onNotFound) onNotFound();
    else showFailure(result.status, result.code);
  }

  // Shows an API failure: groups_required under Groups, everything else as an alert.
  function showFailure(status: number, code: string) {
    const key = knowledgeErrorKey(status, code, "collection");
    if (key === GROUPS_REQUIRED_KEY) setGroupsError(true);
    else setError(key);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (sending) return;
    setGroupsError(false);
    if (name.trim() === "") {
      nameRef.current?.focus();
      return;
    }
    if (level === "restricted" && parseGroups(groupsText).length === 0) {
      setGroupsError(true);
      groupsRef.current?.focus();
      return;
    }
    if (level === "public" && collection?.access_level !== "public") {
      setConfirming(true);
      return;
    }
    void save();
  }

  function confirmPublic() {
    setConfirming(false);
    void save();
  }

  return (
    <>
      <div className="dialog-backdrop">
        <div
          className="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          data-testid="collection-dialog"
          ref={dialogRef}
          onKeyDown={onKeyDown}
        >
          <h2 className="members-card-title" id={titleId}>
            {t(isEdit ? "admin.knowledge.dialog.editTitle" : "admin.knowledge.dialog.createTitle")}
          </h2>
          <form className="dialog-form" noValidate onSubmit={submit}>
            <label className="field">
              <span className="field-label">{t("admin.knowledge.dialog.name")}</span>
              <input
                ref={nameRef}
                name="name"
                className="field-input"
                type="text"
                autoComplete="off"
                maxLength={NAME_MAX}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">{t("admin.knowledge.dialog.subtitle")}</span>
              <input
                name="subtitle"
                className="field-input"
                type="text"
                autoComplete="off"
                maxLength={NAME_MAX}
                value={subtitle}
                onChange={(event) => setSubtitle(event.target.value)}
              />
            </label>
            <div
              className="field"
              role="radiogroup"
              aria-label={t("admin.knowledge.dialog.access")}
            >
              <span className="field-label">{t("admin.knowledge.dialog.access")}</span>
              {LEVELS.map((option) => (
                <label key={option} className="field-option">
                  <input
                    type="radio"
                    name="access-level"
                    value={option}
                    checked={level === option}
                    disabled={accessLocked || (!isEdit && !canManageAccess && option === "public")}
                    onChange={() => setLevel(option)}
                  />
                  <span>{t(`admin.knowledge.access.${option}`)}</span>
                </label>
              ))}
              {accessLocked ? (
                <p className="field-help" data-testid="access-locked-note">
                  {t("admin.knowledge.dialog.accessLocked")}
                </p>
              ) : null}
            </div>
            {level === "restricted" ? (
              <div className="field">
                <label className="field">
                  <span className="field-label">{t("admin.knowledge.dialog.groups")}</span>
                  <input
                    ref={groupsRef}
                    name="groups"
                    className="field-input"
                    type="text"
                    autoComplete="off"
                    value={groupsText}
                    disabled={accessLocked}
                    aria-invalid={groupsError}
                    aria-describedby={
                      groupsError ? `${groupsHelpId} ${groupsErrorId}` : groupsHelpId
                    }
                    onChange={(event) => setGroupsText(event.target.value)}
                  />
                </label>
                <span className="field-help" id={groupsHelpId}>
                  {t("admin.knowledge.dialog.groupsHelp")}
                </span>
                {groupsError ? (
                  <span
                    className="field-error"
                    id={groupsErrorId}
                    role="alert"
                    data-testid="groups-error"
                  >
                    {t(GROUPS_REQUIRED_KEY)}
                  </span>
                ) : null}
              </div>
            ) : null}
            <div className="field">
              <label className="field-option">
                <input
                  type="checkbox"
                  name="local-only"
                  checked={localOnly}
                  disabled={localOnlyLocked}
                  aria-describedby={helpId}
                  onChange={(event) => setLocalOnly(event.target.checked)}
                />
                <span>{t("admin.knowledge.dialog.localOnly")}</span>
              </label>
              <span className="field-help" id={helpId}>
                {t("admin.knowledge.dialog.localOnlyHelp")}
              </span>
            </div>
            {error ? (
              <p className="members-alert" role="alert">
                {t(error)}
              </p>
            ) : null}
            <div className="dialog-actions">
              <button type="button" className="button-secondary" onClick={close}>
                {t("admin.knowledge.dialog.cancel")}
              </button>
              <button ref={submitRef} type="submit" className="button-primary" disabled={sending}>
                {t(isEdit ? "admin.knowledge.dialog.save" : "admin.knowledge.dialog.create")}
              </button>
            </div>
          </form>
        </div>
      </div>
      {confirming ? (
        <ConfirmPublicDialog onConfirm={confirmPublic} onCancel={() => setConfirming(false)} />
      ) : null}
    </>
  );
}
