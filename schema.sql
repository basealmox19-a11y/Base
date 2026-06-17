-- SFC ALMOXARIFADO — SCHEMA COMPLETO
-- Execute TODO no SQL Editor do Supabase
DROP TABLE IF EXISTS movimentacoes CASCADE;
DROP TABLE IF EXISTS documentos CASCADE;
DROP TABLE IF EXISTS produtos CASCADE;
DROP TABLE IF EXISTS categorias CASCADE;
DROP TABLE IF EXISTS setores CASCADE;
DROP TABLE IF EXISTS configuracoes CASCADE;
DROP TABLE IF EXISTS usuarios CASCADE;
DROP SEQUENCE IF EXISTS seq_codigo_produto;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SEQUENCE IF NOT EXISTS seq_codigo_produto START 1000 INCREMENT 1;

CREATE TABLE usuarios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nick TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL DEFAULT 'usuario' CHECK (perfil IN ('admin','almoxarife','usuario')),
    nome TEXT, email TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    primeiro_acesso BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE categorias (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome TEXT UNIQUE NOT NULL, descricao TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE setores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome TEXT UNIQUE NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE produtos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo_interno TEXT UNIQUE NOT NULL DEFAULT '',
    nome TEXT NOT NULL, ean TEXT UNIQUE,
    categoria_id UUID REFERENCES categorias(id) ON DELETE SET NULL,
    unidade_primaria TEXT NOT NULL DEFAULT 'CX',
    unidade_secundaria TEXT NOT NULL DEFAULT 'UN',
    fator_conversao NUMERIC(12,4) NOT NULL DEFAULT 1,
    quantidade_total_secundaria NUMERIC(14,4) NOT NULL DEFAULT 0,
    estoque_minimo_primario NUMERIC(12,4) NOT NULL DEFAULT 0,
    descricao TEXT, ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE documentos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    caminho_arquivo TEXT, nome_arquivo TEXT,
    status_envio TEXT NOT NULL DEFAULT 'pendente' CHECK (status_envio IN ('pendente','enviado','nao_requer')),
    data_upload TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE movimentacoes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    produto_id UUID NOT NULL REFERENCES produtos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida','ajuste')),
    tipo_saida TEXT CHECK (tipo_saida IN ('MANUAL','SOLICITADA')),
    tipo_entrada TEXT CHECK (tipo_entrada IN ('Nota Fiscal','FL','Entrada Interna','Ajuste Manual')),
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','aprovado','rejeitado','concluido','cancelado')),
    quantidade_informada NUMERIC(12,4) NOT NULL DEFAULT 0,
    unidade_informada TEXT NOT NULL DEFAULT 'UN',
    quantidade_convertida NUMERIC(12,4) NOT NULL DEFAULT 0,
    envio_financeiro BOOLEAN NOT NULL DEFAULT FALSE,
    reservado BOOLEAN NOT NULL DEFAULT FALSE,
    notificacao_lida BOOLEAN NOT NULL DEFAULT FALSE,
    motivo_rejeicao TEXT,
    setor_solicitante TEXT, nome_solicitante TEXT, nick_solicitante TEXT,
    motivo_saida TEXT, fornecedor TEXT, numero_nf TEXT, observacao TEXT,
    documento_id UUID REFERENCES documentos(id),
    usuario_solicitante UUID REFERENCES usuarios(id),
    usuario_autorizador UUID REFERENCES usuarios(id),
    usuario_executor UUID REFERENCES usuarios(id),
    data_autorizacao TIMESTAMPTZ, data_movimentacao TIMESTAMPTZ,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE configuracoes (
    chave TEXT PRIMARY KEY, valor TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger: código interno automático
CREATE OR REPLACE FUNCTION fn_codigo_interno() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.codigo_interno IS NULL OR NEW.codigo_interno = '' THEN
        NEW.codigo_interno := 'SFC-' || LPAD(nextval('seq_codigo_produto')::TEXT,5,'0');
    END IF; RETURN NEW;
END;$$;
DROP TRIGGER IF EXISTS trg_codigo ON produtos;
CREATE TRIGGER trg_codigo BEFORE INSERT ON produtos FOR EACH ROW EXECUTE FUNCTION fn_codigo_interno();

-- Trigger: atualiza estoque
CREATE OR REPLACE FUNCTION fn_estoque() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status='concluido' AND (OLD.status IS NULL OR OLD.status<>'concluido') THEN
        IF NEW.tipo='entrada' THEN
            UPDATE produtos SET quantidade_total_secundaria=quantidade_total_secundaria+NEW.quantidade_convertida,atualizado_em=NOW() WHERE id=NEW.produto_id;
        ELSIF NEW.tipo IN ('saida','ajuste') THEN
            UPDATE produtos SET quantidade_total_secundaria=GREATEST(0,quantidade_total_secundaria-NEW.quantidade_convertida),atualizado_em=NOW() WHERE id=NEW.produto_id;
        END IF;
    END IF; RETURN NEW;
END;$$;
DROP TRIGGER IF EXISTS trg_estoque ON movimentacoes;
CREATE TRIGGER trg_estoque AFTER INSERT OR UPDATE ON movimentacoes FOR EACH ROW EXECUTE FUNCTION fn_estoque();

-- RLS
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE categorias ENABLE ROW LEVEL SECURITY;
ALTER TABLE setores ENABLE ROW LEVEL SECURITY;
ALTER TABLE produtos ENABLE ROW LEVEL SECURITY;
ALTER TABLE documentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE movimentacoes ENABLE ROW LEVEL SECURITY;
ALTER TABLE configuracoes ENABLE ROW LEVEL SECURITY;

DO $$ DECLARE t TEXT;
BEGIN FOREACH t IN ARRAY ARRAY['usuarios','categorias','setores','produtos','documentos','movimentacoes','configuracoes']
LOOP
  EXECUTE format('DROP POLICY IF EXISTS svc ON %I',t);
  EXECUTE format('CREATE POLICY svc ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',t);
END LOOP; END $$;

-- Dados padrão
INSERT INTO categorias(nome) VALUES('Limpeza'),('Escritório'),('Informática'),('Ferramentas'),('EPI'),('Elétrico'),('Alimentício'),('Manutenção'),('Outros') ON CONFLICT(nome) DO NOTHING;
INSERT INTO setores(nome) VALUES('Administrativo'),('Financeiro'),('RH'),('TI'),('Manutenção'),('Operações'),('Logística'),('Marketing'),('Comercial'),('Diretoria') ON CONFLICT(nome) DO NOTHING;
INSERT INTO configuracoes(chave,valor) VALUES
  ('email_financeiro','financeiro@empresa.com.br'),
  ('email_assunto','[NF] Nota Fiscal - SFC Almoxarifado'),
  ('email_corpo','Prezados,\n\nSegue nota fiscal.\n\nAtenciosamente,')
ON CONFLICT(chave) DO NOTHING;
