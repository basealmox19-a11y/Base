-- ================================================================
-- SFC Almoxarifado — Patch v3
-- Execute no Supabase SQL Editor
-- NÃO apaga dados existentes — apenas adiciona novos recursos
-- ================================================================

-- Tabela de Solicitações de Compra (nova — não interfere com dados existentes)
CREATE TABLE IF NOT EXISTS solicitacoes_compra (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    produto_descricao TEXT NOT NULL,
    nome_solicitante  TEXT NOT NULL,
    setor_solicitante TEXT NOT NULL,
    nick_solicitante  TEXT,
    usuario_id        UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    status            TEXT NOT NULL DEFAULT 'pendente'
                        CHECK (status IN ('pendente','aprovado','rejeitado')),
    motivo_rejeicao   TEXT,
    usuario_autorizador UUID REFERENCES usuarios(id) ON DELETE SET NULL,
    data_autorizacao  TIMESTAMPTZ,
    observacao        TEXT,
    criado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- RLS para a nova tabela
ALTER TABLE solicitacoes_compra ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS svc ON solicitacoes_compra;
CREATE POLICY svc ON solicitacoes_compra
    FOR ALL TO service_role USING (true) WITH CHECK (true);
