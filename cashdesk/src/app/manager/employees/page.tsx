"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/utils";
import { RequireAuth } from "@/components/require-auth";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Employee = {
  id: number;
  email: string;
  name: string;
  is_active: boolean;
  on_hand: string;
  deposited: string;
  left_to_deposit: string;
  collected: string;
};

function EmployeesPanel() {
  const [items, setItems] = useState<Employee[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const res = await api<{ items: Employee[] }>("/api/staff/employees");
    setItems(res.items);
  }, []);

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setOk("");
    setLoading(true);
    try {
      await api("/api/staff/employees", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
      });
      setName("");
      setEmail("");
      setPassword("");
      setOk("Employee created");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setLoading(false);
    }
  }

  async function toggleActive(emp: Employee) {
    try {
      await api(`/api/staff/employees/${emp.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !emp.is_active }),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        description="Add collectors and monitor who holds cash and how much is left to deposit."
      />

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Add employee</CardTitle>
            <CardDescription>They sign in with this email and password</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={onSubmit}>
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
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
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={6}
                  required
                />
              </div>
              {error ? <p className="text-sm text-red-700">{error}</p> : null}
              {ok ? <p className="text-sm text-emerald-700">{ok}</p> : null}
              <Button type="submit" disabled={loading}>
                {loading ? "Creating…" : "Create employee"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Team balances</CardTitle>
          </CardHeader>
          <CardContent className="px-0 pb-0">
            <Table>
              <THead>
                <TR>
                  <TH>Employee</TH>
                  <TH>On hand</TH>
                  <TH>Deposited</TH>
                  <TH>Left</TH>
                  <TH></TH>
                </TR>
              </THead>
              <TBody>
                {items.length === 0 ? (
                  <TR>
                    <TD colSpan={5} className="py-8 text-center text-stone-500">
                      No employees yet
                    </TD>
                  </TR>
                ) : (
                  items.map((emp) => (
                    <TR key={emp.id}>
                      <TD>
                        <div className="font-medium">{emp.name}</div>
                        <div className="text-xs text-stone-500">{emp.email}</div>
                        <Badge variant={emp.is_active ? "success" : "muted"} className="mt-1">
                          {emp.is_active ? "active" : "inactive"}
                        </Badge>
                      </TD>
                      <TD>{money(emp.on_hand)}</TD>
                      <TD>{money(emp.deposited)}</TD>
                      <TD className="font-medium">{money(emp.left_to_deposit)}</TD>
                      <TD className="text-right">
                        <Button size="sm" variant="outline" onClick={() => toggleActive(emp)}>
                          {emp.is_active ? "Deactivate" : "Activate"}
                        </Button>
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

export default function EmployeesPage() {
  return (
    <RequireAuth role="manager">{() => <EmployeesPanel />}</RequireAuth>
  );
}
