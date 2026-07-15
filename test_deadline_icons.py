# Automatic Notion deadline icons

This project checks the **Master Tasks** data source once per day and changes each task's native Notion page icon according to its **Due Date**.

## Rules

| Situation | Icon |
|---|---|
| Status is `Done` | Green circle |
| Overdue or due in 0–2 days | Red circle |
| Due in 3–7 days | Orange circle |
| Due more than 7 days away | Light-grey circle |
| No Due Date | Existing icon is left alone |

The project is already configured for:

- Data source: `Master Tasks`
- Data source ID: `39ecd388-8383-8019-bbf8-000b7ff88754`
- Due-date property: `Due Date`
- Status property: `Status`
- Completed status: `Done`
- Time zone: `Europe/London`

## 1. Create a Notion internal connection

1. Open the Notion developer portal.
2. Create a new **internal connection** called `Deadline Icons`.
3. Give it **Read content** and **Update content** capabilities.
4. Copy the installation access token. Keep it private.

## 2. Give the connection access to Master Tasks

Open the original **Master Tasks** database in Notion — not merely a linked view.

Use the page menu:

`••• → Connections → Add connection → Deadline Icons`

Confirm access.

## 3. Put these files in GitHub

1. Create a new GitHub repository.
2. Upload every file and folder from this package, including `.github/workflows/update-icons.yml`.
3. In the repository, open:

`Settings → Secrets and variables → Actions → New repository secret`

4. Name the secret exactly:

`NOTION_TOKEN`

5. Paste the Notion token as its value.

Never place the token directly inside a code file.

## 4. Test it

1. Open the repository's **Actions** tab.
2. Select **Update Notion deadline icons**.
3. Choose **Run workflow**.
4. Open the run and check the log.

After a successful test, it will run automatically every day at **07:15 Europe/London**.

## Customising the thresholds

Edit `.github/workflows/update-icons.yml`:

```yaml
RED_DAYS: "2"
ORANGE_DAYS: "7"
```

## Safe test mode

Before the first real run, you can temporarily set:

```yaml
DRY_RUN: "true"
```

The workflow will report what it *would* change without modifying Notion. Change it back to `"false"` when satisfied.

## Troubleshooting

### `404 object_not_found`

The connection does not have access to the original Master Tasks database, or the wrong data-source ID is being used.

### `403 restricted_resource`

The connection needs the **Update content** capability.

### The workflow runs but nothing changes

Check that tasks have a value in `Due Date`, and that the property is still named exactly `Due Date`.

### Scheduled run did not happen

Scheduled GitHub workflows run from the default branch. Open the Actions tab and confirm that Actions are enabled for the repository.
