"use client";

import { FileCode2, Fingerprint, Router, Server, ShieldCheck, UserCog } from "lucide-react";

import { PageHeader } from "@/components/common/page-header";
import { EventsTab } from "@/components/tacacs/events-tab";
import { NasTab } from "@/components/tacacs/nas-tab";
import { PoliciesTab } from "@/components/tacacs/policies-tab";
import { PreviewTab } from "@/components/tacacs/preview-tab";
import { ServersTab } from "@/components/tacacs/servers-tab";
import { UsersTab } from "@/components/tacacs/users-tab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/use-url-state";

export default function TacacsPage() {
  const [state, setState] = useUrlState({ tab: "servers" });
  return (
    <>
      <PageHeader title="TACACS+" description="Centralised device AAA: servers, NAS clients, authorisation policies and users." />
      <Tabs value={state.tab} onValueChange={(v) => setState({ tab: v })}>
        <TabsList>
          <TabsTrigger value="servers"><Server /> Servers</TabsTrigger>
          <TabsTrigger value="nas"><Router /> NAS devices</TabsTrigger>
          <TabsTrigger value="policies"><ShieldCheck /> Policies</TabsTrigger>
          <TabsTrigger value="users"><UserCog /> Users</TabsTrigger>
          <TabsTrigger value="preview"><FileCode2 /> Config preview</TabsTrigger>
          <TabsTrigger value="events"><Fingerprint /> Auth events</TabsTrigger>
        </TabsList>
        <TabsContent value="servers"><ServersTab /></TabsContent>
        <TabsContent value="nas"><NasTab /></TabsContent>
        <TabsContent value="policies"><PoliciesTab /></TabsContent>
        <TabsContent value="users"><UsersTab /></TabsContent>
        <TabsContent value="preview"><PreviewTab /></TabsContent>
        <TabsContent value="events"><EventsTab /></TabsContent>
      </Tabs>
    </>
  );
}
