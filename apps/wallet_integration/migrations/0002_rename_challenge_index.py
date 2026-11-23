from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wallet_integration", "0001_initial")]

    operations = [
        migrations.RenameIndex(
            model_name="walletlinkchallenge",
            old_name="wallet_link_challenge_user_exp_idx",
            new_name="wallet_link_user_exp_idx",
        ),
    ]
