"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  API_BASE,
  getCachedUser,
  getToken,
  homeFor,
  setCachedUser,
  setToken,
  type StaffUser,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [signedIn, setSignedIn] = useState<StaffUser | null>(null);

  useEffect(() => {
    const cached = getCachedUser();
    if (getToken() && cached) setSignedIn(cached);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api<{ token: string; user: StaffUser }>("/api/staff/login", {
        method: "POST",
        body: JSON.stringify({ email: email.trim(), password }),
      });
      setToken(res.token);
      setCachedUser(res.user);
      router.replace(homeFor(res.user));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      console.error("[Finance login]", { api: API_BASE, email, error: message });
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,_#ccfbf1_0%,_transparent_40%),radial-gradient(circle_at_80%_0%,_#fef3c7_0%,_transparent_35%),linear-gradient(180deg,_#fafaf9,_#f5f5f4)]" />
      <Card className="relative z-10 w-full max-w-md border-stone-200/80 shadow-lg">
        <CardHeader>
          <p className="font-serif text-3xl text-teal-950">Finance</p>
          <CardTitle className="text-lg">Sign in</CardTitle>
          <CardDescription>
            Employees collect cash. Managers review transactions and deposits. Admins control people
            and settings. Each address opens only for that account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {signedIn ? (
            <div className="mb-4 rounded-lg border border-stone-200 bg-stone-50 px-3 py-3 text-sm text-stone-700">
              <p>
                This browser is signed in as <span className="font-medium">{signedIn.name}</span> (
                {signedIn.role}). Open a page for a different role only after you sign in with that
                account below.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => router.push(homeFor(signedIn))}
              >
                Continue as {signedIn.name}
              </Button>
            </div>
          ) : null}
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
