"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, API_BASE, setToken, type StaffUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api<{ token: string; user: StaffUser }>("/api/staff/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(res.token);
      router.replace(res.user.role === "manager" ? "/manager" : "/employee");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      console.error("[Cash Desk login]", { api: API_BASE, email, error: message });
      setError(`${message} (API: ${API_BASE})`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,_#ccfbf1_0%,_transparent_40%),radial-gradient(circle_at_80%_0%,_#fef3c7_0%,_transparent_35%),linear-gradient(180deg,_#fafaf9,_#f5f5f4)]" />
      <Card className="relative z-10 w-full max-w-md border-stone-200/80 shadow-lg">
        <CardHeader>
          <p className="font-serif text-3xl text-teal-950">Cash Desk</p>
          <CardTitle className="text-lg">Sign in</CardTitle>
          <CardDescription>
            Employees collect cash. Managers oversee deposits and ledger. Sign in with the manager
            email set in Railway as <code className="text-xs">STAFF_BOOTSTRAP_MANAGER_EMAIL</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error ? <p className="text-sm text-red-700">{error}</p> : null}
            <Button className="w-full" type="submit" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
