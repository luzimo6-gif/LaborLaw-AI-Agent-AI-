import { formBindingData, FormExtensionAbility, formInfo } from '@kit.FormKit';
import { Want } from '@kit.AbilityKit';
import { LawCardStateService } from '../services/LawCardStateService';

export default class LawFormAbility extends FormExtensionAbility {
  onAddForm(want: Want): formBindingData.FormBindingData {
    const formId: string = this.formIdFromWant(want);
    LawCardStateService.registerForm(this.context, formId);
    return LawCardStateService.bindingData(this.context);
  }

  onUpdateForm(formId: string): void {
    LawCardStateService.updateForm(this.context, formId).catch(() => {
      // 系统刷新失败时保留卡片上一次可用数据。
    });
  }

  onRemoveForm(formId: string): void {
    LawCardStateService.removeForm(this.context, formId);
  }

  onAcquireFormState(want: Want): formInfo.FormState {
    return formInfo.FormState.READY;
  }

  private formIdFromWant(want: Want): string {
    if (want.parameters === undefined) {
      return '';
    }
    const value: Object | undefined = want.parameters[formInfo.FormParam.IDENTITY_KEY];
    return typeof value === 'string' ? value : '';
  }
}
