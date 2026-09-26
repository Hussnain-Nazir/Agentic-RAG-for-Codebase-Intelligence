import { useState } from "react";
import { ItemList } from "./ItemList";
import { LoginForm } from "./LoginForm";
import { RegisterForm } from "./RegisterForm";

export function App() {
  const [token, setToken] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  return <main>
    <h1>My items</h1>
    {token ? <ItemList token={token} /> : registering
      ? <><RegisterForm onRegistered={() => setRegistering(false)} /><button onClick={() => setRegistering(false)}>Sign in instead</button></>
      : <><LoginForm onLogin={setToken} /><button onClick={() => setRegistering(true)}>Create an account</button></>}
  </main>;
}
