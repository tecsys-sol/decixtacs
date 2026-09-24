"use client";

import { FileCode2, FileUp, Fingerprint, Router, Server, ShieldCheck, UserCog } from "lucide-react";
import * as React from "react";

import { PageHeader } from "@/components/common/page-header";
import { EventsTab } from "@/components/tacacs/events-tab";
import { ImportTacPlusDialog } from "@/components/tacacs/import-dialog";
import { NasTab } from "@/components/tacacs/nas-tab";
import { PoliciesTab } from "@/components/tacacs/policies-tab";
import { PreviewTab } from "@/components/tacacs/preview-tab";
import { ServersTab } from "@/components/tacacs/servers-tab";
import { UsersTab } from "@/components/tacacs/users-tab";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/use-auth";
import { useUrlState } from "@/hooks/use-url-state";

export default function TacacsPage() {
  const [state, setState] = useUrlState({ tab: "servers" });
  const [importOpen, setImportOpen] = React.useState(false);
  const { can } = useAuth();
  return (
    <>
      <PageHeader
        title="TACACS+"
        description="Centralised device AAA: servers, NAS clients, authorisation policies and users."
        actions={
          can("tacacs:write") ? (
            <Button variant="outline" onClick={() => setImportOpen(true)}>
              <FileUp /> Import tac_plus config
            </Button>
          ) : null
        }
      />
      <ImportTacPlusDialog open={importOpen} onOpenChange={setImportOpen} />
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
