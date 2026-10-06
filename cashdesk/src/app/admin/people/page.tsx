"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Person = {
  id: number;
  email: string;
  name: string;
  role: "admin" | "manager" | "employee" | string;
  is_active: boolean;
};

function PeoplePage() {
  const [items, setItems] = useState<Person[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Person["role"]>("employee");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const res = await api<{ items: Person[] }>("/api/staff/admin/people");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Could not load people"));
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setOk("");
    setLoading(true);
    try {
      await api("/api/staff/admin/people", {
        method: "POST",
        body: JSON.stringify({ name, email, password, role }),
      });
      setName("");
      setEmail("");
      setPassword("");
      setRole("employee");
      setOk("Account created");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setLoading(false);
    }
  }

  async function patchPerson(person: Person, body: Record<string, unknown>, done: string) {
    setError("");
    setOk("");
    try {
      await api(`/api/staff/admin/people/${person.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setOk(done);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  function resetPassword(person: Person) {
    const next = window.prompt(`New password for ${person.name} (at least 6 characters)`);
    if (!next) return;
    if (next.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    patchPerson(person, { password: next }, `Password updated for ${person.name}`);
  }

  function changeRole(person: Person, nextRole: string) {
    if (nextRole === person.role) return;
    patchPerson(person, { role: nextRole }, `${person.name} is now ${nextRole}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="People"
        description="Add a developer admin, a finance manager, or a cash-desk employee."
      />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Add person</CardTitle>
            <CardDescription>They sign in on this same Cash Desk login.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={onSubmit}>
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input id="password" type="password" minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="role">Role</Label>
                <select
                  id="role"
                  className="h-10 w-full rounded-md border border-stone-300 bg-white px-3 text-sm"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="employee">Employee</option>
                  <option value="manager">Finance manager</option>
                  <option value="admin">Developer admin</option>
                </select>
              </div>
              {error ? <p className="text-sm text-red-700">{error}</p> : null}
              {ok ? <p className="text-sm text-emerald-700">{ok}</p> : null}
              <Button type="submit" disabled={loading}>
                {loading ? "Creating…" : "Create account"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Accounts</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Role / status</TH>
                  <TH></TH>
                </TR>
              </THead>
              <TBody>
                {items.length === 0 ? (
                  <TR>
                    <TD colSpan={3} className="py-8 text-center text-stone-500">
                      No accounts yet
                    </TD>
                  </TR>
                ) : (
                  items.map((person) => (
                    <TR key={person.id}>
                      <TD>
                        <div className="font-medium">{person.name}</div>
                        <div className="text-xs text-stone-500">{person.email}</div>
                      </TD>
                      <TD>
                        <div className="flex flex-col gap-1">
                          <select
                            aria-label={`Role for ${person.name}`}
                            className="h-8 rounded-md border border-stone-300 bg-white px-2 text-xs"
                            value={person.role}
                            onChange={(e) => changeRole(person, e.target.value)}
                          >
                            <option value="employee">employee</option>
                            <option value="manager">manager</option>
                            <option value="admin">admin</option>
                          </select>
                          <Badge variant={person.is_active ? "success" : "muted"} className="w-fit">
                            {person.is_active ? "active" : "inactive"}
                          </Badge>
                        </div>
                      </TD>
                      <TD className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="ghost" onClick={() => resetPassword(person)}>
                            Reset password
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              patchPerson(
                                person,
                                { is_active: !person.is_active },
                                person.is_active
                                  ? `${person.name} deactivated`
                                  : `${person.name} activated`
                              )
                            }
                          >
                            {person.is_active ? "Deactivate" : "Activate"}
                          </Button>
                        </div>
                      </TD>
                    </TR>
                  ))
                )}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function AdminPeoplePage() {
  return <RequireAuth role="admin">{() => <PeoplePage />}</RequireAuth>;
}
