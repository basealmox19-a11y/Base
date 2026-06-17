-- SFC Almoxarifado — Patch v2
-- Execute no Supabase SQL Editor (não apaga dados existentes)

-- Novos campos em movimentacoes
ALTER TABLE movimentacoes ADD COLUMN IF NOT EXISTS reservado BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movimentacoes ADD COLUMN IF NOT EXISTS notificacao_lida BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE movimentacoes ADD COLUMN IF NOT EXISTS motivo_rejeicao TEXT;

-- Novos campos em usuarios
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS primeiro_acesso BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha_alterada_em TIMESTAMPTZ;

-- Marca usuários existentes como não-primeiro-acesso (já fizeram login antes)
-- Comente esta linha se quiser forçar troca de senha para todos
UPDATE usuarios SET primeiro_acesso = FALSE WHERE primeiro_acesso = TRUE;
