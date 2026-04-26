# DOCX templates

Place the APN PoC DOCX export template here manually:

```text
agent/templates/apn-poc-template.docx
```

Upload it to the artifacts S3 bucket with:

```bash
infra/scripts/upload_template.sh
```

The script uploads the file to:

```text
s3://<artifacts-bucket>/templates/apn-poc-template.docx
```

This directory intentionally does not include the DOCX file.
