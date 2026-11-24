GRANT SELECT,
    INSERT (servicio_id, version, cliente_sub, estado, telefono_verificado_e164),
    UPDATE (intentos, disponible_desde, publicado_en)
    ON TABLE public.servicio_outbox TO servitech_app;
