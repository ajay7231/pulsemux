import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { useSession } from "../../app/SessionProvider";
import { workspaceKey } from "../../app/useWorkspaceQueries";
import { Button } from "../../components/ui";
import { resourceService } from "../../services/platform";

/** Bounded remote audience selection. Selected IDs survive searches and pages. */
export function ContactPicker({
  value,
  onChange,
  multiple = false,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  multiple?: boolean;
}) {
  const { session } = useSession();
  const id = useId();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 250);
    useEffect(() => {
      if (contacts.data && page > Math.max(1, contacts.data.pages))
        setPage(Math.max(1, contacts.data.pages));
    }, [contacts.data?.pages, page]);
    return () => clearTimeout(timer);
  }, [search]);
  const contacts = useQuery({
    queryKey: [
      ...workspaceKey(session!.workspace.id),
      "resources",
      "contacts",
      { query, page, picker: true },
    ],
    queryFn: ({ signal }) =>
      resourceService.list(
        "contacts",
        { search: query, page, pageSize: 25 },
        signal,
      ),
  });
  return (
    <div className="contact-picker">
      <label className="field" htmlFor={id}>
        <span>Search contacts</span>
        <input
          id={id}
          type="search"
          maxLength={200}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Name, phone number, or timezone"
        />
      </label>
      <div role="status" aria-live="polite" className="muted">
        {value.length} selected
        {contacts.data ? ` · ${contacts.data.total} matching contacts` : ""}
      </div>
      {contacts.isPending && <p role="status">Loading contacts…</p>}
      {contacts.isError && (
        <div role="alert">
          <p>Contacts could not be loaded.</p>
          <Button onClick={() => void contacts.refetch()}>Retry</Button>
        </div>
      )}
      <div
        className="audience-list"
        role="group"
        aria-label={multiple ? "Campaign audience" : "Outbound contact"}
      >
        {contacts.data?.items.map((contact) => (
          <label className="checkbox-line" key={contact.id}>
            <input
              type={multiple ? "checkbox" : "radio"}
              name={id + "-contact"}
              disabled={!contact.consent || contact.opted_out}
              checked={value.includes(contact.id)}
              onChange={(e) =>
                onChange(
                  multiple
                    ? e.target.checked
                      ? [...value, contact.id]
                      : value.filter((item) => item !== contact.id)
                    : [contact.id],
                )
              }
            />
            {contact.name}
            <small>
              {contact.phone}
              {!contact.consent || contact.opted_out ? " · not eligible" : ""}
            </small>
          </label>
        ))}
        {contacts.data?.total === 0 && <p>No contacts match this search.</p>}
      </div>
      <div className="row-actions">
        <Button
          disabled={page <= 1 || contacts.isFetching}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </Button>
        <span>
          Page {page} of {Math.max(1, contacts.data?.pages || 1)}
        </span>
        <Button
          disabled={
            !contacts.data || page >= contacts.data.pages || contacts.isFetching
          }
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
        <Button disabled={!value.length} onClick={() => onChange([])}>
          Clear selection
        </Button>
      </div>
    </div>
  );
}
