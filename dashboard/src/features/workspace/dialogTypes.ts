import type { Dispatch, SetStateAction } from "react";
import type { Row } from "../../lib/types";
export type WorkspaceDialogContentProps = {
  draft: Row;
  selected: Row | null;
  setDraft: Dispatch<SetStateAction<Row>>;
  setModal: Dispatch<SetStateAction<string>>;
  run: (fn: () => Promise<void>) => Promise<void>;
  saveDone: (message: string) => void;
  setDocuments: Dispatch<SetStateAction<Row[]>>;
  setNotice: Dispatch<SetStateAction<string>>;
  documents: Row[];
  busy: boolean;
  canEdit: boolean;
  isAdmin: boolean;
  refresh: () => void;
};

export type DialogFieldProps = {
  draft: Row;
  setDraft: Dispatch<SetStateAction<Row>>;
  input: (
    key: string,
    type?: string,
    required?: boolean,
  ) => import("react").JSX.Element;
  select: (
    key: string,
    items: Row[],
    label?: string,
    empty?: string,
  ) => import("react").JSX.Element;
  session: import("../../contracts/schemas").Session;
  timezones: string[];
  modal: string;
  agents: Row[];
  numbers: Row[];
};
