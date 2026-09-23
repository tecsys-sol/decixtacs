"use client";

import { KeySquare, Link2, LogIn, Users, UsersRound } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BindingsTab } from "@/components/users/bindings-tab";
import { GroupsTab } from "@/components/users/groups-tab";
import { LoginsTab } from "@/components/users/logins-tab";
import { RolesTab } from "@/components/users/roles-tab";
import { UsersTab } from "@/components/users/users-tab";
import { useUrlState } from "@/hooks/use-url-state";

export default function UsersPage() {
  const [f, setF] = useUrlState({ tab: "users" });
  return (
    <>
      <PageHeader title="Users & access" description="Platform identities, groups, roles and scoped role bindings." />
      <Tabs value={f.tab} onValueChange={(v) => setF({ tab: v })}>
        <TabsList>
          <TabsTrigger value="users"><Users /> Users</TabsTrigger>
          <TabsTrigger value="groups"><UsersRound /> Groups</TabsTrigger>
          <TabsTrigger value="roles"><KeySquare /> Roles</TabsTrigger>
          <TabsTrigger value="bindings"><Link2 /> Role bindings</TabsTrigger>
          <TabsTrigger value="logins"><LogIn /> Login history</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><UsersTab /></TabsContent>
        <TabsContent value="groups"><GroupsTab /></TabsContent>
        <TabsContent value="roles"><RolesTab /></TabsContent>
        <TabsContent value="bindings"><BindingsTab /></TabsContent>
        <TabsContent value="logins"><LoginsTab /></TabsContent>
      </Tabs>
    </>
  );
}
