#include "UESynthCaptureModule.h"

DEFINE_LOG_CATEGORY_STATIC(LogUESynthCapture, Log, All);

void FUESynthCaptureModule::StartupModule()
{
    UE_LOG(LogUESynthCapture, Log, TEXT("UESynthCapture module loaded."));
}

void FUESynthCaptureModule::ShutdownModule()
{
    UE_LOG(LogUESynthCapture, Log, TEXT("UESynthCapture module unloaded."));
}

IMPLEMENT_MODULE(FUESynthCaptureModule, UESynthCapture)
