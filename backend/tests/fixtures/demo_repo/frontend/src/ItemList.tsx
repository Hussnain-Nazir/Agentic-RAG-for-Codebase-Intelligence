import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { createItem, deleteItem, listItems, updateItem } from "./api";
import type { Item } from "./types";

export function ItemList({ token }: { token: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void listItems(token).then(setItems).catch(() => setError("Items could not be loaded"));
  }, [token]);

  async function addItem(event: FormEvent) {
    event.preventDefault();
    try {
      const item = await createItem(token, title);
      setItems((current) => [...current, item]);
      setTitle("");
    } catch { setError("Item could not be created"); }
  }

  async function renameItem(item: Item) {
    const next = window.prompt("New title", item.title);
    if (!next) return;
    try {
      const updated = await updateItem(token, item.id, next);
      setItems((current) => current.map((value) => value.id === item.id ? updated : value));
    } catch { setError("Item could not be updated"); }
  }

  async function removeItem(item: Item) {
    try {
      await deleteItem(token, item.id);
      setItems((current) => current.filter((value) => value.id !== item.id));
    } catch { setError("Item could not be deleted"); }
  }

  return <section>
    <form onSubmit={addItem}><label>New item <input value={title} onChange={(event) => setTitle(event.target.value)} /></label><button type="submit">Add</button></form>
    <ul>{items.map((item) => <li key={item.id}>{item.title} <button onClick={() => void renameItem(item)}>Rename</button> <button onClick={() => void removeItem(item)}>Delete</button></li>)}</ul>
    {error && <p role="alert">{error}</p>}
  </section>;
}
